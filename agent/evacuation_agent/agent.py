"""Challenge 4 ADK Root Agent & Maps Grounding Sub-Agent Architecture.

Combines:
- Persona & Intent Classifier (`classify_persona_and_intent`) for Local Planner vs. Hospital/Clinical personas
- Option 1 (Primary Spine): Ghost Shelter & Accessibility Auditor (`audit_county_shelters`)
- Option 2: Zero-Car Transit Lifeline (`find_zero_car_transit_gaps`)
- Option 3: Generator-Blind Nursing Home Alert (`check_medical_power_gaps`)
- Live Grounding with Google Maps + Routing (`verify_place_with_maps_grounding` + `maps_grounding_subagent`)
- Post-Hoc Equity & Paperwork Bias Audit (`run_equity_audit`)
- Operator Field Inspection Write-Back Loop (`record_field_assessment`)
- Google-Managed BigQuery MCP Server integration (`get_managed_bigquery_mcp_toolset`)
"""

from __future__ import annotations

import os
from typing import Any, List

import google.auth
import google.auth.transport.requests
from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from typing_extensions import override

from .config import DEFAULT_COUNTY_FIPS, MODEL_NAME, PROJECT_ID
from .tools import (
    audit_county_shelters,
    check_medical_power_gaps,
    classify_persona_and_intent,
    find_zero_car_transit_gaps,
    record_field_assessment,
    run_equity_audit,
    verify_place_with_maps_grounding,
)


class GoogleMapsGroundingTool(BaseTool):
    """Built-in Gemini Grounding with Google Maps tool for ADK sub-agents."""

    def __init__(self) -> None:
        super().__init__(
            name="google_maps_grounding",
            description="Built-in Gemini Grounding with Google Maps tool.",
        )

    @override
    async def process_llm_request(
        self,
        *,
        tool_context: ToolContext,
        llm_request: Any,
    ) -> None:
        llm_request.config = llm_request.config or types.GenerateContentConfig()
        llm_request.config.tools = llm_request.config.tools or []
        llm_request.config.tools.append(
            types.Tool(google_maps=types.GoogleMaps())
        )


google_maps_grounding = GoogleMapsGroundingTool()


class ManagedBigQueryMCPToolset(BaseToolset):
    """Fault-tolerant ADK Toolset connected to Google's Managed BigQuery MCP Server.

    Lazily authenticates against `https://bigquery.googleapis.com/mcp` with
    `x-goog-user-project` set to PROJECT_ID, and gracefully falls back to
    native BigQuery FunctionTools if the remote MCP endpoint is unavailable.
    """

    def __init__(self) -> None:
        super().__init__()
        self._inner: Any = None

    @override
    async def get_tools(self, readonly_context: Any = None) -> List[BaseTool]:
        if os.environ.get("ENABLE_MANAGED_MCP", "1").lower() not in ("1", "true", "yes"):
            return []
        try:
            if self._inner is None:
                from google.adk.tools.mcp_tool import (
                    MCPToolset,
                    StreamableHTTPConnectionParams,
                )

                creds, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                auth_req = google.auth.transport.requests.Request()
                creds.refresh(auth_req)

                self._inner = MCPToolset(
                    connection_params=StreamableHTTPConnectionParams(
                        url="https://bigquery.googleapis.com/mcp",
                        headers={
                            "Authorization": f"Bearer {creds.token}",
                            "x-goog-user-project": PROJECT_ID,
                        },
                    )
                )
            return await self._inner.get_tools(readonly_context)
        except Exception:
            return []

    @override
    async def close(self) -> None:
        if self._inner is not None:
            try:
                await self._inner.close()
            except Exception:
                pass


def get_managed_bigquery_mcp_toolset() -> BaseToolset:
    """Return a fault-tolerant ManagedBigQueryMCPToolset instance."""
    return ManagedBigQueryMCPToolset()


MAPS_SUBAGENT_INSTRUCTION = """You are the Live Google Maps Grounding Specialist for the County Evacuation Readiness Agent.
When asked to verify a shelter or nursing home:
1. Query ONE building name and ONE street address at a time. Never issue a generic county-wide query.
2. Report clearly:
   - What facility currently occupies that street address according to Google Maps.
   - Whether the facility has been RENAMED since 2022 (same building/address, different current name).
   - Whether Google Maps shows the facility as currently open or permanently/temporarily closed.
   - If origin coordinates are provided, report the driving route distance/time and walking distance/time.
3. Always include the attribution `<span translate="no">Google Maps</span>` immediately after every grounded claim.
"""

maps_grounding_subagent = Agent(
    name="maps_grounding_specialist",
    model=MODEL_NAME,
    description=(
        "Dedicated sub-agent holding the built-in google_maps_grounding tool to verify "
        "individual shelter and nursing home buildings one street address at a time."
    ),
    instruction=MAPS_SUBAGENT_INSTRUCTION,
    tools=[google_maps_grounding],
)


ROOT_SYSTEM_INSTRUCTION = f"""You are the **Adaptive Evacuation Readiness & Vulnerable Community Planning Agent** for **Lee County, Florida (`county_fips = '{DEFAULT_COUNTY_FIPS}'`)**, operating in **mid-August** before peak Atlantic hurricane season.

Your user may be speaking or typing from one of two operational personas:
1. **`LOCAL_PLANNER` (County Emergency Management / Municipal Transit Planner)**: Focused on shelter storm-surge de-designation, `UNRECORDED` ADA wheelchair inspection triage, zero-car census tract LeeTran bus staging, and SVI paperwork gap remedies.
2. **`HOSPITAL` (Hospital / Clinical Readiness & Transfer Coordinator)**: Focused on CMS nursing homes (`certified_beds`), backup generator verification, HHS emPOWER electricity-dependent Medicare DME beneficiaries (`13,402` in Lee County), and clinical transfer routing to inland Special Medical Needs shelters.

Always call `classify_persona_and_intent(question)` first when answering a user prompt so you explicitly acknowledge their identified persona (`LOCAL_PLANNER` or `HOSPITAL`) and provide concrete, actionable recommendations tailored to their question.

### MANDATORY EPISTEMIC & DATA-DEFECT GUARDRAILS (NEVER VIOLATE)
1. **Unrecorded != No (`NULL` is an Epistemic Gap, Not a Negative Fact)**:
   - In `evacuation_readiness.shelters`, boolean flags (`wheelchair_accessible`, `generator_onsite`, `self_sufficient_electricity`, `in_surge_slosh_area`, `in_100_yr_floodplain`) are `TRUE`, `FALSE`, or `NULL`.
   - `NULL` means **UNRECORDED** (nobody wrote it down in the 2022 FEMA registry).
   - NEVER report "0 accessible shelters" or "no generator" when the column is `NULL`. Always state all three numbers: confirmed `YES` (`TRUE`), confirmed `NO` (`FALSE`), and `UNRECORDED` (`NULL`).
2. **Never Use `ada_compliant`**:
   - The `ada_compliant` column is a national decoy (only 63 `TRUE` rows out of 53,942 nationally). Always use `wheelchair_accessible`.
3. **Florida CDC PLACES `pct_lacktrpt` Trap**:
   - In Florida, `pct_lacktrpt` is 100% `NULL`. Always rank transit vulnerability using ACS `households_no_vehicle` and CDC SVI `pct_no_vehicle`, and state transparently that this measures household vehicle ownership.
4. **HHS emPOWER County-Scale & `11`-Censoring Guardrail**:
   - `power_dependent_counties` is strictly **county-level**. NEVER disaggregate or allocate county electricity-dependent DME counts to individual census tracts.
   - Check `power_dependent_is_censored`: a value of `11` means `1 to 10` (HIPAA small-number suppression).
5. **Distinguish Historical Federal Registry vs. Live Google Maps Grounding**:
   - Explicitly label which facts come from the **2022 FEMA / ACS / SVI / NRI / CMS static registry** in BigQuery and which facts were **verified live seconds ago via Grounding with Google Maps**.
   - Always verify specific candidate shelters or nursing homes **one building name + one street address at a time** using `verify_place_with_maps_grounding` (or `maps_grounding_specialist`).
6. **Mandatory `<span translate="no">Google Maps</span>` Attribution**:
   - Immediately following every Google Maps-grounded claim, include the clickable source title/URI and the exact attribution `<span translate="no">Google Maps</span>` unmodified.
   - Never cache or export raw Google Maps content; only `place_id` pointers may be persisted via `record_field_assessment`.

### STRUCTURE EVERY READINESS BRIEF INTO FOUR PILLARS
1. **Pillar 1 — Where Need Concentrates (Option 2: Zero-Car Transit Lifeline & Option 3: Power-Dependent Residents)**:
   - Top carless census tracts (`households_no_vehicle`, `pct_no_vehicle`), disability & mobility prevalence, mobile homes, CMS nursing homes (`certified_beds`), and county-wide HHS emPOWER electricity-dependent Medicare beneficiaries.
2. **Pillar 2 — What Can Meet It & What Is Exposed (Option 1: Ghost Shelter & Surge Audit + Live Maps Grounding)**:
   - Which shelters are inside the SLOSH storm-surge zone (`in_surge_slosh_area IS TRUE`) or 100-year floodplain, `EVAC` vs. `POST` usage, straight-line (`ST_DISTANCE`) vs. live road routing gaps (`> 2.0 km` Walkability Wall), and live Google Maps verification catching renamed or closed facilities.
3. **Pillar 3 — What We Cannot Verify From Here (The Epistemic Honesty Ledger)**:
   - Exact count and percentage of `UNRECORDED` wheelchair accessibility (`93%` in Lee County), `UNRECORDED` backup generators (`94%`), `UNRECORDED` surge flags (`97%`), Florida's unrecorded `pct_lacktrpt`, and post-hoc equity audit findings (`run_equity_audit`).
4. **Pillar 4 — Concrete August Pre-Season Action List**:
   - **Action 1 (August Ground-Truth Inspection Triage)**: Exact top 3 high-capacity shelters with `UNRECORDED` accessibility/generator flags or surge exposure to physically inspect this week (and demonstrate live write-back via `record_field_assessment`).
   - **Action 2 (T-Minus 48h Municipal Bus Staging)**: Exact pickup coordinates (`lat`, `lon`) and bus allocations for the top 5 carless tracts exceeding the 2.0 km Walkability Wall.
   - **Action 3 (Nursing Home Backup Power Mutual-Aid)**: Pre-September transfer & generator verification protocol for the county's largest nursing homes.
"""


def _build_tools() -> List[Any]:
    tools: List[Any] = [
        classify_persona_and_intent,
        audit_county_shelters,
        find_zero_car_transit_gaps,
        check_medical_power_gaps,
        verify_place_with_maps_grounding,
        run_equity_audit,
        record_field_assessment,
        AgentTool(agent=maps_grounding_subagent),
    ]
    if os.environ.get("ENABLE_MANAGED_MCP", "1").lower() in ("1", "true", "yes"):
        try:
            tools.append(get_managed_bigquery_mcp_toolset())
        except Exception:
            # Graceful fallback to native BigQuery FunctionTools if MCP endpoint is unreachable
            pass
    return tools


root_agent = Agent(
    name="evacuation_readiness_agent",
    model=MODEL_NAME,
    description=(
        "Adaptive Evacuation Readiness & Vulnerable Community Planning Agent for Lee County, FL. "
        "Identifies Local Planner vs. Hospital/Clinical personas from voice/text prompts and "
        "audits FEMA shelters, zero-car census tracts, and power-dependent nursing homes using "
        "BigQuery spatial SQL, Managed MCP, and live Grounding with Google Maps."
    ),
    instruction=ROOT_SYSTEM_INSTRUCTION,
    tools=_build_tools(),
)
