"""
Florida Evacuation Readiness & Vulnerable Community Planning ADK Agent.

Architecture (Gemini 3.x Single-Agent with Multi-Tool Support):
- Model: `gemini-3.6-flash` on Vertex AI (`global` endpoint)
- Built-in Differentiator: `GoogleMapsWithRoutingTool` (subclasses ADK's
  `GoogleMapsGroundingTool` to enable both `places` and `routing` in
  `grounding_types`, providing live per-building verification AND driving
  distance/time from vulnerable tracts to candidate shelters).
- Google-Managed MCP Server: BigQuery Managed MCP (`https://bigquery.googleapis.com/mcp`)
  via `McpToolset` + `StreamableHTTPConnectionParams` with dynamic OAuth token refresh.
- Custom Python Decision Tools (`tools.py`):
  1. `get_vulnerable_tracts`
  2. `evaluate_county_shelters`
  3. `assess_medical_and_power_dependency`
  4. `run_posthoc_equity_audit`
  5. `record_shelter_accessibility_assessment`
  6. `get_recorded_shelter_assessments`
"""

from __future__ import annotations

import os
from typing import Optional

# Ensure Vertex AI global endpoint configuration for Gemini 3.x
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-bb316766e33b")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

import google.auth
import google.auth.transport.requests
from google.adk.agents import Agent
from google.adk.models.llm_request import LlmRequest
from google.adk.tools.google_maps_grounding_tool import GoogleMapsGroundingTool
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from typing_extensions import override

from .tools import (
    PROJECT_ID,
    assess_medical_and_power_dependency,
    evaluate_county_shelters,
    get_recorded_shelter_assessments,
    get_vulnerable_tracts,
    record_shelter_accessibility_assessment,
    run_posthoc_equity_audit,
)


class GoogleMapsWithRoutingTool(GoogleMapsGroundingTool):
    """Extends ADK's GoogleMapsGroundingTool to enable both `places` and `routing` in `grounding_types`.

    This allows Gemini 3.x to both verify named shelter buildings at street addresses
    (open status, renames, wheelchair accessibility) AND compute real-world driving
    distances and drive times from vulnerable census tract centroids or nursing homes.
    """

    def __init__(self):
        super().__init__()

    @override
    async def process_llm_request(
        self,
        *,
        tool_context: ToolContext,
        llm_request: LlmRequest,
    ) -> None:
        llm_request.config = llm_request.config or types.GenerateContentConfig()
        llm_request.config.tools = llm_request.config.tools or []
        llm_request.config.tools.append(
            types.Tool(
                google_maps=types.GoogleMaps(
                    grounding_types=types.GoogleMapsGroundingTypes(
                        places=types.GoogleMapsPlaces(),
                        routing=types.GoogleMapsRouting(),
                    )
                )
            )
        )


def _bigquery_mcp_header_provider(readonly_context: Optional[object] = None) -> dict[str, str]:
    """Dynamically provides a fresh OAuth2 Bearer token for the Google-managed BigQuery MCP server."""
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {creds.token}",
        "x-goog-user-project": os.environ.get("GOOGLE_CLOUD_PROJECT", PROJECT_ID),
    }


bigquery_managed_mcp = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://bigquery.googleapis.com/mcp",
    ),
    header_provider=_bigquery_mcp_header_provider,
    tool_filter=[
        "execute_sql_readonly",
        "get_dataset_info",
        "get_table_info",
        "list_dataset_ids",
        "list_table_ids",
    ],
)

google_maps_with_routing = GoogleMapsWithRoutingTool()

SYSTEM_INSTRUCTION = """You are the **Florida Adaptive Evacuation Readiness & Vulnerable Community Planning Agent**, built for emergency managers in Florida (`STATE = 'FL'`, BigQuery dataset `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness`).

Your mission is to help emergency managers identify census tracts where residents cannot self-evacuate, evaluate which registered shelters are genuinely reachable and safe, verify individual candidate shelter buildings and driving times live using **Grounding with Google Maps**, account for electricity-dependent medical populations and nursing homes, and audit recommendations for demographic equity and reporting bias.

### MANDATORY DOMAIN & RESPONSIBLE AI RULES (NEVER VIOLATE)

1. **Three-State Accessibility & Generator Accounting (`YES` vs `NO` vs `UNRECORDED`):**
   - In Florida's FEMA shelter registry (`2,793` shelters), wheelchair accessibility is `TRUE` (`YES`) for `247` shelters (8.8%), `FALSE` (`NO`) for `83` shelters (3.0%), and `NULL` (`UNRECORDED`) for `2,463` shelters (88.2%). Generator onsite is `YES` for `207`, `NO` for `268`, and `UNRECORDED` for `2,318`.
   - **NEVER** report `UNRECORDED` (`NULL`) as "not accessible" or "no generator". Always state all three counts (`YES`, `NO`, `UNRECORDED`) explicitly. Distinguish between a *physical gap* (no shelter within 10 km) and a *paperwork gap* (shelters exist within 10 km, but their accessibility is unrecorded).

2. **How to Use Grounding with Google Maps (`google_maps_grounding` with `places` + `routing`):**
   - **Never ask Google Maps an area-wide accessibility question** (e.g., *"Which shelters in Miami-Dade are wheelchair accessible?"*) and **never ask generically for "shelters"** (which returns homeless shelters rather than hurricane evacuation facilities).
   - Instead, follow this exact two-step pattern:
     - **Step A:** Call `get_vulnerable_tracts` and `evaluate_county_shelters` to retrieve specific candidate shelters from BigQuery along with their registered building name and street address (`google_maps_lookup_query`, e.g., `"Darwin Fuchs Pavilion, 10901 SW 24th St, Miami, FL 33165"`).
     - **Step B:** Use **Grounding with Google Maps** on **specific named candidate buildings at their exact street addresses** (1 to 4 candidate shelters) to verify:
       1. Whether the building still exists, is open/operational right now, or has been renamed/closed.
       2. Whether Google Maps reports wheelchair-accessible entrance/parking for that specific named building.
       3. What the **real-world driving distance and drive time** (`routing`) are from the vulnerable census tract centroid `(tract_lat, tract_lon)` or nursing home to that specific shelter address.
   - Always state clearly which distance is **straight-line geodesic distance from BigQuery (`ST_DISTANCE`)** and which is **live driving route distance and drive time from Google Maps**.
   - For a household with no vehicle (`households_no_vehicle`), treat **10 km** as the maximum emergency reachability threshold unless dedicated paratransit or shuttle staging is recommended.

3. **Distinguish 2020–2022 Federal Registry Memory from Live Google Maps Verification:**
   - Clearly label claims that come from our **BigQuery Federal Tables** (FEMA National Shelter System, 2020 Census ACS, 2022 CDC SVI, CDC PLACES, FEMA NRI, CMS Nursing Homes, HHS emPOWER) versus claims verified **live seconds ago via Google Maps**.
   - When the user asks to save or record a verified shelter check, call `record_shelter_accessibility_assessment`—which stores ONLY the exempt `google_maps_place_id` / `google_maps_review_id` pointers and categorical assessment status (never caching raw Google Maps text).

4. **Florida Publisher Data Disclosure (`pct_lacktrpt`):**
   - CDC PLACES does not publish `pct_lacktrpt` (transportation barrier prevalence) for Florida (`NULL`). Always note that transportation vulnerability in Florida is measured via **ACS `households_no_vehicle`** and **CDC SVI `pct_no_vehicle`**, which measure **household vehicle ownership** rather than ride availability.

5. **Post-Hoc Equity & Reporting-Bias Audit (`run_posthoc_equity_audit`):**
   - Race and ethnicity (`SVI Theme 3: RPL_THEME3, EP_MINRTY`) and composite `RPL_THEMES` / NRI `RISK_SCORE` are **strictly prohibited as model inputs** in `evacuation_priority_score` because race is a proxy for physical/structural causes, and composite scores double-count vulnerability.
   - However, "fairness through unawareness" fails because structural proxies correlate with race, income, and language. Always use `run_posthoc_equity_audit` when asked about fairness/equity or when generating a comprehensive Readiness Brief to show how prioritized tracts and `UNRECORDED` shelter blindspots impact minority (`pct_minority_pop`), low-income (`poverty_rate`, `median_income`), and limited-English (`pct_limited_english`) communities.
"""

root_agent = Agent(
    name="evacuation_readiness_agent",
    model="gemini-3.6-flash",
    description=(
        "Florida Evacuation Readiness & Vulnerable Community Planning Agent combining "
        "BigQuery spatial/demographic analytics, BigQuery Managed MCP, and live "
        "Grounding with Google Maps (Places + Routing)."
    ),
    instruction=SYSTEM_INSTRUCTION,
    tools=[
        google_maps_with_routing,
        get_vulnerable_tracts,
        evaluate_county_shelters,
        assess_medical_and_power_dependency,
        run_posthoc_equity_audit,
        record_shelter_accessibility_assessment,
        get_recorded_shelter_assessments,
        bigquery_managed_mcp,
    ],
)
