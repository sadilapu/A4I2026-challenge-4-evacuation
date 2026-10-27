# Your agent goes here

This folder is empty on purpose.

We built the on-ramp: every registered shelter in your state with capacity and accessibility, the
census tracts around them with disability, vehicle access and age, the counties where people depend
on electricity for medical equipment, hurricane and coastal-flood exposure per tract, and a
validation suite that tells you plainly whether any of it is wrong. We did not build the vehicle.
The design decisions in your agent are what you are judged on.

## What has to be true of what you build here

- **An ADK agent**, in Python.
- **At least one tool you built yourself.** A Python function tool, or one you defined in MCP
  Toolbox—either counts. The obvious candidate wraps a shelter query. The more valuable one holds
  the logic that is not a single query: deciding what "reachable" means for a household with no
  vehicle, weighing an unrecorded accessibility flag against a recorded one, turning a list of
  tracts into a readiness brief with a recommendation attached. Consuming only prebuilt generic
  tools and calling that your design does not count.
- **At least one Google-managed MCP server, consumed.** Do not author your own—use BigQuery's
  built-in server or the [MCP Toolbox for Databases](https://github.com/googleapis/mcp-toolbox).
- **Deployed to Google Cloud**—Agent Runtime or Cloud Run, your choice.
- **Your required differentiator: Grounding with Google Maps, genuinely used.** Your agent must
  call it and act on what comes back. Naming it in a slide does not count, and neither does calling
  it once for decoration in a flow that would give the same answer without it.

## Your model choice decides your architecture

**On Gemini 2.5 and older**, a built-in tool cannot share an agent with a function tool of your own:

```
400 INVALID_ARGUMENT—"Unable to submit request because Multiple tools are supported
only when they are all search tools."
```

**On Gemini 3.x it works.** Verified 2026-08-09: `google_maps_grounding` and a BigQuery function
tool in one ADK agent, run end to end, both firing in a single turn. The same request on
`gemini-2.5-flash` still returns the 400.

**Use a 3.x model and keep one agent.** If you pin an older one, you need two, and it is a fine
architecture either way:

- a **maps agent** holding `google_maps_grounding` and nothing else
- your **root agent** holding your function tools, an MCP server, and the maps agent wrapped in
  `AgentTool`

`GoogleMapsGroundingTool` takes no constructor arguments and does not accept
`bypass_multi_tools_limit`, so on an older model the sub-agent is the only route. `google_maps` and
`google_search` coexist on any model.

**Ignore this warning**—it appears once per turn and means nothing here:
`Tools at indices [0] are not compatible with automatic function calling (AFC). AFC is disabled.`
ADK runs its own function-calling loop.

## What Grounding with Google Maps will and will not do

| Will | Will not |
|---|---|
| Find places, addresses, ratings, opening hours | Give you a drive time unless `routing` is in `grounding_types` |
| Tell you whether somewhere is open **right now** | Know anything in our tables—who lives nearby, wheelchair flags, generators |
| Tell you a place has closed, or been renamed | Answer anything but English |
| Say honestly when it does not know | Answer an *area* question about accessibility |

**Accessibility depends on how you ask.** An area question gets you nothing. **One named building at
one address** got a definite answer 5 times out of 8 in our testing, and agreed with FEMA 4 times
out of 5 where both had a view. Iterating over your candidate shelters one at a time is a real
strategy and almost nobody will try it.

Routing is available too: add `routing` to `grounding_types` alongside `places` and the same grounded
call returns drive times and directions ([Routing—Find Directions](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/grounding/grounding-with-google-maps#routing-find-directions)).
That is the add-on that turns the straight-line distances in our tables into something a planner can
use—the tables themselves carry straight-line distance only. Routing is newer than the rest of the
feature, so if you build on it, test it early. Five to eight seconds per grounded call is normal,
not a bug.

Attribution is a requirement, not a nicety: display the Google Maps sources immediately after the
content they support, viewable within one user interaction, with the words "Google Maps" unmodified
and `translate="no"`. You may keep `place_id` and `review_id`; you may not cache, store or export
the rest of what comes back.

## The thing worth remembering while you build

**Our data knows what a place *is*. Maps knows whether it is *still there*. Neither knows whether it
works for the person you are trying to help.**

FEMA's file is a historical registry. We checked fifteen Florida shelters against Google Maps:
**fourteen still exist, one had been renamed** (same building, new name—a name-only lookup misses
it). So the value of a runtime check is not finding rubble, it is catching the ones that moved or
changed, and knowing what a place is *now*.

The accessibility gap is the harder one. For roughly two thirds of American shelters **nobody has
written it down**, and no amount of grounding creates a record that does not exist.

An agent that reports "no accessible shelters nearby" when it means "nobody recorded any" has
stated a fact about paperwork as a fact about buildings. An agent that says *"eleven of these I can
speak to, sixty-four nobody has assessed"* is more useful, more honest, and will score better.

See the README's "Six defects you will meet" for the data traps and Section 13 of the notebook for
the constraints.


---

## Implemented ADK Agent & Emergency Operations Center UI (`agent/`)

### Architecture (`gemini-3.6-flash` on Vertex AI)
- **[`evacuation_agent/agent.py`](./evacuation_agent/agent.py)**:
  - **`root_agent` (`evacuation_readiness_agent`):** Built with `google-adk` on `gemini-3.6-flash` (`GOOGLE_GENAI_USE_VERTEXAI=True`, `GOOGLE_CLOUD_LOCATION=global`), combining built-in Grounding with Google Maps, custom Python decision tools, and BigQuery's Google-managed MCP server in a single agent.
  - **`GoogleMapsWithRoutingTool`:** Subclasses `GoogleMapsGroundingTool` to enable both `places` and `routing` in `types.GoogleMapsGroundingTypes`, allowing the agent to verify specific named shelter buildings at street addresses AND compute real-world driving distance and drive time from vulnerable tract centroids or nursing homes.
  - **Google-Managed BigQuery MCP Server (`bigquery_managed_mcp`):** Connected to `https://bigquery.googleapis.com/mcp` via `McpToolset` + `StreamableHTTPConnectionParams` with automatic OAuth2 token refresh (`execute_sql_readonly`, `get_dataset_info`, `get_table_info`, `list_dataset_ids`, `list_table_ids`).
- **[`evacuation_agent/tools.py`](./evacuation_agent/tools.py)**:
  - `get_vulnerable_tracts`: Ranks census tracts by structural evacuation barriers (`evacuation_priority_score`) and 10 km shelter reachability (`YES` / `NO` / `UNRECORDED`).
  - `evaluate_county_shelters`: Evaluates county shelter capacity, 3-state accessibility/generator reporting gaps, storm-surge/floodplain flags, and candidate shelter addresses for per-building Google Maps grounding.
  - `assess_medical_and_power_dependency`: Joins HHS emPOWER electricity-dependent Medicare DME populations and CMS nursing homes (`care_facilities`) against designated medical-needs and generator-equipped shelters.
  - `run_posthoc_equity_audit`: Audits prioritized tracts and 10 km reachability tiers post-hoc against `evacuation_readiness.equity_audit_svi_theme3` (`RPL_THEME3`, `EP_MINRTY`), poverty rate, median income, and limited-English proficiency.
  - `record_shelter_accessibility_assessment` & `get_recorded_shelter_assessments`: Persists and retrieves verified shelter assessments and exempt Google Maps `place_id` / `review_id` pointers in `evacuation_readiness.shelter_assessments`.
- **[`app.py`](./app.py) & [`static/index.html`](./static/index.html)**:
  - FastAPI server and Emergency Operations Center (EOC) Readiness Brief web application with strict inline `<span translate="no">Google Maps</span>` attribution mapped via `groundingSupports` (`segment.start_index` safely defaulting `None` to `0`) and `groundingChunks[].maps`.

### Running Locally or Deploying to Cloud Run
```bash
# Run with ADK Web UI
cd agent
adk web

# Run the Emergency Operations Center Readiness Brief Web App
cd agent
uvicorn app:app --host 0.0.0.0 --port 8080

# Deploy to Google Cloud Run
gcloud run deploy fl-evacuation-readiness \
  --source ./agent \
  --region us-central1 \
  --project qwiklabs-gcp-03-bb316766e33b \
  --allow-unauthenticated
```
