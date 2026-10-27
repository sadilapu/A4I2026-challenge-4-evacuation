"""FastAPI Web Server & ADK Runtime Endpoint for Challenge 4 Evacuation Readiness Agent.

Exposes:
- GET  /                        -> Interactive 4-Pillar Readiness Brief & Live ADK Agent UI
- GET  /api/health              -> System & BigQuery / Vertex AI / Managed MCP health check
- GET  /api/brief/{county_fips} -> Full 4-Pillar Readiness Brief (Options 1, 2, 3 + Live Maps Grounding)
- POST /api/verify-place        -> On-demand single-facility Google Maps Grounding + Routing check
- POST /api/field-assessment    -> Write-back field inspection to BigQuery (`shelter_assessments`)
- POST /api/chat                -> Conversational turn executed via ADK `Runner` (`root_agent`)
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field

from evacuation_agent.agent import root_agent
from evacuation_agent.config import (
    DATASET,
    DEFAULT_COUNTY_FIPS,
    LOCATION,
    MODEL_NAME,
    PROJECT_ID,
)
import base64
from evacuation_agent.tools import (
    audit_county_shelters,
    build_persona_action_response,
    check_medical_power_gaps,
    classify_persona_and_intent,
    find_zero_car_transit_gaps,
    record_field_assessment,
    run_equity_audit,
    transcribe_voice_audio,
    verify_place_with_maps_grounding,
)

app = FastAPI(
    title="A4I 2026 Challenge 4 — Adaptive Evacuation Readiness Agent",
    description=(
        "County Emergency Manager Readiness Brief & ADK Agent combining BigQuery spatial SQL, "
        "Google-Managed MCP, and live Grounding with Google Maps."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

APP_NAME = "evacuation_readiness_app"
session_service = InMemorySessionService()
adk_runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)


class VerifyPlaceRequest(BaseModel):
    place_name: str = Field(..., description="Facility name from 2022 FEMA/CMS registry")
    address: str = Field(..., description="Street address")
    city: str = Field(default="Fort Myers", description="City name")
    state: str = Field(default="FL", description="Two-letter state abbreviation")
    origin_lat: Optional[float] = Field(
        default=None, description="Optional origin latitude for live routing"
    )
    origin_lon: Optional[float] = Field(
        default=None, description="Optional origin longitude for live routing"
    )
    origin_label: str = Field(
        default="", description="Optional label for origin coordinates"
    )


class FieldAssessmentRequest(BaseModel):
    shelter_id: int
    shelter_name: str
    county_name: str = "Lee"
    fema_wheelchair_status: str = "UNRECORDED"
    assessed_wheelchair_status: str = "FIELD_VERIFIED_YES"
    operational_status: str = "OPEN"
    google_maps_place_id: str = ""
    inspector_notes: str = ""


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    user_id: str = "county_emergency_manager"
    county_fips: str = DEFAULT_COUNTY_FIPS


class VoiceTranscribeRequest(BaseModel):
    audio_base64: str = Field(..., description="Base64-encoded audio from microphone")
    mime_type: str = Field(default="audio/webm", description="MIME type of recorded audio")


class PersonaActionRequest(BaseModel):
    question: str
    county_fips: str = DEFAULT_COUNTY_FIPS


@app.get("/", response_class=HTMLResponse)
async def serve_index() -> Any:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="UI index.html not found")
    return FileResponse(str(index_path))


@app.get("/api/health")
async def health_check() -> Dict[str, Any]:
    return {
        "status": "ok",
        "project_id": PROJECT_ID,
        "bigquery_dataset": f"{PROJECT_ID}.{DATASET}",
        "vertex_ai_location": LOCATION,
        "primary_model": MODEL_NAME,
        "default_county_fips": DEFAULT_COUNTY_FIPS,
        "agent_name": root_agent.name,
        "tools_registered": [
            getattr(t, "__name__", getattr(t, "name", type(t).__name__))
            for t in root_agent.tools
        ],
    }


@app.get("/api/brief/{county_fips}")
async def generate_county_readiness_brief(
    county_fips: str = DEFAULT_COUNTY_FIPS,
    include_live_maps: bool = True,
) -> Dict[str, Any]:
    """Run all 4 Readiness Brief pillars + parallel live Google Maps Grounding."""
    loop = asyncio.get_running_loop()

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_shelters = loop.run_in_executor(
            pool, audit_county_shelters, county_fips, 12
        )
        f_transit = loop.run_in_executor(
            pool, find_zero_car_transit_gaps, county_fips, 5
        )
        f_medical = loop.run_in_executor(
            pool, check_medical_power_gaps, county_fips, 8
        )
        f_equity = loop.run_in_executor(pool, run_equity_audit, county_fips)

        shelter_audit, transit_gaps, medical_gaps, equity_audit = await asyncio.gather(
            f_shelters, f_transit, f_medical, f_equity
        )

    live_grounding_results: List[Dict[str, Any]] = []
    if include_live_maps and shelter_audit.get("status") == "ok":
        triage_targets: List[Dict[str, Any]] = []

        # 1. Include top surge-exposed shelter + top high-capacity unrecorded shelter + nursing home rename check
        surge_list = shelter_audit.get("surge_or_flood_exposed_shelters", [])
        if surge_list:
            triage_targets.append(surge_list[0])

        for cand in shelter_audit.get("august_field_inspection_top3", []):
            if len(triage_targets) >= 2:
                break
            if all(t["shelter_id"] != cand["shelter_id"] for t in triage_targets):
                triage_targets.append(cand)

        # Also include Lehigh Acres Healthcare & Rehab Center from Option 3 to demonstrate live rename detection
        for nh in medical_gaps.get("top_nursing_homes", []):
            if "LEHIGH ACRES" in nh.get("provider_name", "").upper():
                triage_targets.append(
                    {
                        "shelter_id": 0,
                        "shelter_name": nh["provider_name"],
                        "address_1": nh["provider_address"],
                        "city": nh["city"],
                        "state": nh["state"],
                        "effective_capacity": nh["certified_beds"],
                        "fema_2022_record": {"provenance": "2022 CMS Care Facilities Registry"},
                        "audit_flags": ["CMS Nursing Home — verify current operating name & backup power"],
                    }
                )
                break

        # Attach #1 carless tract coordinates to the first target for live routing comparison
        top_tract = (
            transit_gaps.get("priority_zero_car_tracts", [None])[0]
            if transit_gaps.get("status") == "ok"
            else None
        )

        def _verify_one(idx_and_target: tuple[int, Dict[str, Any]]) -> Dict[str, Any]:
            idx, item = idx_and_target
            o_lat, o_lon, o_label = None, None, ""
            if idx == 0 and top_tract:
                coords = top_tract.get("pickup_staging_coordinates", {})
                o_lat = coords.get("lat")
                o_lon = coords.get("lon")
                o_label = f"Top Carless Tract {top_tract.get('geo_id')} ({top_tract.get('households_no_vehicle')} no-vehicle households)"

            res = verify_place_with_maps_grounding(
                place_name=item["shelter_name"],
                address=item.get("address_1") or "",
                city=item.get("city") or "Fort Myers",
                state=item.get("state") or "FL",
                origin_lat=o_lat,
                origin_lon=o_lon,
                origin_label=o_label,
            )
            res["shelter_id"] = item["shelter_id"]
            res["effective_capacity"] = item.get("effective_capacity", 0)
            res["fema_2022_record"] = item.get("fema_2022_record", {})
            res["audit_flags"] = item.get("audit_flags", [])
            return res

        with ThreadPoolExecutor(max_workers=3) as maps_pool:
            futures = [
                loop.run_in_executor(maps_pool, _verify_one, (i, tgt))
                for i, tgt in enumerate(triage_targets)
            ]
            live_grounding_results = list(await asyncio.gather(*futures))

    return {
        "status": "ok",
        "county_fips": county_fips,
        "option_1_shelter_audit": shelter_audit,
        "option_2_zero_car_transit_lifeline": transit_gaps,
        "option_3_medical_power_alert": medical_gaps,
        "post_hoc_equity_audit": equity_audit,
        "live_maps_grounding_spotlights": live_grounding_results,
    }


@app.post("/api/verify-place")
async def api_verify_place(req: VerifyPlaceRequest) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        verify_place_with_maps_grounding,
        req.place_name,
        req.address,
        req.city,
        req.state,
        req.origin_lat,
        req.origin_lon,
        req.origin_label,
    )


@app.post("/api/field-assessment")
async def api_record_field_assessment(req: FieldAssessmentRequest) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        record_field_assessment,
        req.shelter_id,
        req.shelter_name,
        req.county_name,
        req.fema_wheelchair_status,
        req.assessed_wheelchair_status,
        req.operational_status,
        req.google_maps_place_id,
        req.inspector_notes,
    )


@app.post("/api/voice-transcribe")
async def api_voice_transcribe(req: VoiceTranscribeRequest) -> Dict[str, Any]:
    """Transcribe browser microphone audio via Vertex AI Gemini 2.5 Flash."""
    loop = asyncio.get_running_loop()
    raw_bytes = base64.b64decode(req.audio_base64)
    transcript = await loop.run_in_executor(
        None,
        transcribe_voice_audio,
        raw_bytes,
        req.mime_type,
    )
    persona_info = classify_persona_and_intent(transcript)
    return {
        "status": "ok",
        "transcript": transcript,
        "persona_info": persona_info,
    }


@app.post("/api/persona-action")
async def api_persona_action(req: PersonaActionRequest) -> Dict[str, Any]:
    """Fast persona identification and dynamic actionable UI deck builder."""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        build_persona_action_response,
        req.question,
        req.county_fips,
    )
    return {"status": "ok", **result}


@app.post("/api/chat")
async def api_chat(req: ChatRequest) -> Dict[str, Any]:
    """Execute a conversational turn through the ADK Runner (`root_agent`) + parallel Persona Action builder."""
    loop = asyncio.get_running_loop()
    persona_future = loop.run_in_executor(
        None,
        build_persona_action_response,
        req.message,
        req.county_fips,
    )

    session_id = req.session_id or f"sess-{uuid.uuid4().hex[:10]}"
    existing = await session_service.get_session(
        app_name=APP_NAME,
        user_id=req.user_id,
        session_id=session_id,
    )
    if existing is None:
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=req.user_id,
            session_id=session_id,
        )

    user_content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=req.message)],
    )

    response_texts: List[str] = []
    tool_calls_made: List[Dict[str, Any]] = []
    grounding_sources: List[Dict[str, str]] = []

    async for event in adk_runner.run_async(
        user_id=req.user_id,
        session_id=session_id,
        new_message=user_content,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "function_call", None):
                    fc = part.function_call
                    tool_calls_made.append(
                        {
                            "tool_name": fc.name,
                            "args": dict(fc.args) if fc.args else {},
                        }
                    )
                if getattr(part, "function_response", None):
                    fr = part.function_response
                    resp_dict = dict(fr.response) if fr.response else {}
                    if "google_maps_sources" in resp_dict:
                        for src in resp_dict.get("google_maps_sources", []):
                            if src not in grounding_sources:
                                grounding_sources.append(src)
                if getattr(part, "text", None) and event.is_final_response():
                    response_texts.append(part.text)

        gm = getattr(event, "grounding_metadata", None)
        if gm and getattr(gm, "grounding_chunks", None):
            for ch in gm.grounding_chunks:
                maps_obj = getattr(ch, "maps", None)
                if maps_obj:
                    src_item = {
                        "title": getattr(maps_obj, "title", "") or "Google Maps Place",
                        "uri": getattr(maps_obj, "uri", "") or "",
                        "place_id": getattr(maps_obj, "place_id", "") or "",
                    }
                    if src_item not in grounding_sources:
                        grounding_sources.append(src_item)

    persona_payload = await persona_future
    final_reply = "\n\n".join(t.strip() for t in response_texts if t.strip())
    return {
        "status": "ok",
        "session_id": session_id,
        "reply": final_reply,
        "tool_calls": tool_calls_made,
        "google_maps_sources": grounding_sources,
        "persona_action": persona_payload,
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
