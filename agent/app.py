"""
FastAPI Web Application & API Server for the Florida Evacuation Readiness ADK Agent.

Features:
- Executes `root_agent` (`gemini-3.6-flash` + `GoogleMapsWithRoutingTool` + BigQuery
  Managed MCP + custom Python tools) via ADK's `InMemoryRunner`.
- Extracts `grounding_metadata.grounding_chunks` (`maps.place_id`, `maps.title`, `maps.uri`)
  and `grounding_metadata.grounding_supports` (`segment.start_index` treated safely as 0
  when `None`, `segment.end_index`, `grounding_chunk_indices`) to render Google Maps
  attribution immediately following the content it supports with `<span translate="no">Google Maps</span>`.
- Provides REST endpoints for county readiness summaries, top vulnerable tracts,
  post-hoc equity audit results, and recorded shelter assessments (`place_id` pointers).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel

from evacuation_agent.agent import root_agent
from evacuation_agent.tools import (
    assess_medical_and_power_dependency,
    evaluate_county_shelters,
    get_recorded_shelter_assessments,
    get_vulnerable_tracts,
    record_shelter_accessibility_assessment,
    run_posthoc_equity_audit,
)

APP_NAME = "fl_evacuation_readiness"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Florida Adaptive Evacuation Readiness & Vulnerable Community Planning",
    description="ADK Agent + Grounding with Google Maps (Places & Routing) + BigQuery Managed MCP",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
_sessions: dict[str, str] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default_em_session"
    user_id: str = "emergency_manager"


class AssessmentRequest(BaseModel):
    shelter_id: int
    shelter_name: str
    county_name: str
    fema_wheelchair_status: str
    assessed_wheelchair_status: str
    operational_status: str
    google_maps_place_id: str = ""
    google_maps_review_id: str = ""
    inspector_notes: str = ""


def _extract_grounding_payload(events: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extracts deduplicated Google Maps grounding chunks and segment supports from ADK events.

    Follows Section 13 guidance:
    - `segment.start_index` is `None` on the first segment—always treat `None` as `0`.
    - `confidence_scores` is not populated—never depend on it.
    """
    chunks: list[dict[str, Any]] = []
    supports: list[dict[str, Any]] = []
    seen_uris: dict[str, int] = {}

    for ev in events:
        gm = getattr(ev, "grounding_metadata", None)
        if not gm:
            continue

        chunk_index_map: dict[int, int] = {}
        raw_chunks = getattr(gm, "grounding_chunks", None) or []
        for idx, ch in enumerate(raw_chunks):
            maps_obj = getattr(ch, "maps", None)
            if maps_obj:
                uri = getattr(maps_obj, "uri", "") or ""
                title = getattr(maps_obj, "title", "") or "Verified Place"
                place_id = getattr(maps_obj, "place_id", "") or ""
                key = uri or place_id or title
                if key not in seen_uris:
                    seen_uris[key] = len(chunks)
                    chunks.append(
                        {
                            "index": len(chunks),
                            "title": title,
                            "uri": uri,
                            "place_id": place_id,
                        }
                    )
                chunk_index_map[idx] = seen_uris[key]

        raw_supports = getattr(gm, "grounding_supports", None) or []
        for sup in raw_supports:
            seg = getattr(sup, "segment", None)
            if not seg:
                continue
            start_idx = getattr(seg, "start_index", None)
            if start_idx is None:
                start_idx = 0
            end_idx = getattr(seg, "end_index", None) or 0
            seg_text = getattr(seg, "text", "") or ""
            raw_indices = getattr(sup, "grounding_chunk_indices", None) or []
            mapped_indices = [chunk_index_map[i] for i in raw_indices if i in chunk_index_map]
            if seg_text and mapped_indices:
                supports.append(
                    {
                        "start_index": int(start_idx),
                        "end_index": int(end_idx),
                        "text": seg_text,
                        "chunk_indices": mapped_indices,
                    }
                )

    return chunks, supports


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "project": os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-bb316766e33b"),
        "dataset": "evacuation_readiness",
        "state": "FL",
        "model": root_agent.model,
    }


@app.get("/api/overview")
def api_overview(county: str = Query(default="Miami-Dade")) -> dict[str, Any]:
    """Returns live BigQuery readiness metrics for the selected county (or statewide)."""
    tracts_data = get_vulnerable_tracts(county_name=county, limit=8)
    shelters_data = evaluate_county_shelters(county_name=county or "Miami-Dade", limit=10)
    medical_data = assess_medical_and_power_dependency(county_name=county, limit=6)
    audit_data = run_posthoc_equity_audit(county_name=county)
    assessments_data = get_recorded_shelter_assessments(county_name=county)
    return {
        "county": county or "Statewide (FL)",
        "tracts": tracts_data,
        "shelters": shelters_data,
        "medical_and_power": medical_data,
        "equity_audit": audit_data,
        "recorded_assessments": assessments_data,
    }


@app.post("/api/assessments")
def api_record_assessment(req: AssessmentRequest) -> dict[str, Any]:
    """Records a verified shelter assessment and Google Maps `place_id` pointer to BigQuery."""
    return record_shelter_accessibility_assessment(
        shelter_id=req.shelter_id,
        shelter_name=req.shelter_name,
        county_name=req.county_name,
        fema_wheelchair_status=req.fema_wheelchair_status,
        assessed_wheelchair_status=req.assessed_wheelchair_status,
        operational_status=req.operational_status,
        google_maps_place_id=req.google_maps_place_id,
        google_maps_review_id=req.google_maps_review_id,
        inspector_notes=req.inspector_notes,
    )


@app.post("/api/chat")
async def api_chat(req: ChatRequest) -> dict[str, Any]:
    """Runs the ADK Evacuation Readiness Agent and returns response text, tool trace, and Google Maps grounding metadata."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    session_key = f"{req.user_id}:{req.session_id}"
    if session_key not in _sessions:
        session = await runner.session_service.create_session(
            app_name=APP_NAME,
            user_id=req.user_id,
        )
        _sessions[session_key] = session.id

    adk_session_id = _sessions[session_key]
    user_msg = types.Content(role="user", parts=[types.Part.from_text(text=req.message)])

    events = []
    tool_calls: list[dict[str, Any]] = []
    response_parts: list[str] = []

    async for ev in runner.run_async(
        user_id=req.user_id,
        session_id=adk_session_id,
        new_message=user_msg,
    ):
        events.append(ev)
        if ev.content and ev.content.parts:
            for part in ev.content.parts:
                if part.function_call:
                    tool_calls.append(
                        {
                            "name": part.function_call.name,
                            "args": dict(part.function_call.args or {}),
                        }
                    )
                if part.text:
                    response_parts.append(part.text)

    full_text = "".join(response_parts).strip()
    grounding_chunks, grounding_supports = _extract_grounding_payload(events)

    return {
        "reply": full_text,
        "tool_calls": tool_calls,
        "grounding_chunks": grounding_chunks,
        "grounding_supports": grounding_supports,
        "has_google_maps_grounding": len(grounding_chunks) > 0,
    }


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> Any:
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse("<h1>Florida Evacuation Readiness Agent API is running.</h1>")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
