# EvacPulse AI — Agent Architecture & Problem/Solution Reference (`agent/`)

**Live Cloud Run Service**: [https://evacuation-readiness-agent-360663039447.us-central1.run.app](https://evacuation-readiness-agent-360663039447.us-central1.run.app)

## Problem & Solution Overview

### Problem
County emergency managers and hospital planners in Florida must prepare pre-season hurricane evacuation briefs using fragmented federal datasets where:
- **88% of Florida shelters (`shelters`) have `NULL` (unrecorded) wheelchair accessibility**, which naive tools conflate with `"No"`.
- **Static 2022 FEMA/CMS registries** cannot tell if a building has closed, moved, or changed its name, nor can BigQuery `ST_DISTANCE` provide real-world road drive times across bridges for zero-vehicle households (`vulnerability_tracts`).
- **CMS nursing homes (`care_facilities`) and HHS emPOWER electricity-dependent populations (`power_dependent_counties`)** are disconnected from nearby generator-backed (`generator_onsite = TRUE`), storm-surge-safe (`in_surge_slosh_area = FALSE`) shelters.

### Solution (`EvacPulse AI`)
This directory contains the production **Google ADK (`google-adk`)** multi-agent system, FastAPI server, and plain-English geospatial web workspace:
- [`evacuation_agent/agent.py`](evacuation_agent/agent.py): Defines `root_agent` + `maps_grounding_subagent` (`AgentTool`) + Google-Managed BigQuery MCP toolset (`McpToolset`).
- [`evacuation_agent/tools.py`](evacuation_agent/tools.py): Parallelized BigQuery spatial SQL tools (`audit_county_shelters`, `find_zero_car_transit_gaps`, `check_medical_power_gaps`, `run_equity_audit`), live **Grounding with Google Maps** (`verify_place_with_maps_grounding`), BigQuery field inspection write-back (`record_field_assessment`), dynamic 67-county Florida resolver (`resolve_county_from_query`), and **Gemini 2.5 Flash TTS (`Kore`)** paraphrased voice synthesis (`synthesize_natural_speech_wav`).
- [`server.py`](server.py): FastAPI web runtime serving `/`, `/api/persona-action`, `/api/chat`, `/api/verify-place`, `/api/field-assessment`, `/api/voice-transcribe`, and `/api/voice-tts`.
- [`static/index.html`](static/index.html): Non-technical, role-adaptive emergency readiness UI with interactive in-map overlays, dynamic county switching, and voice-input-triggered audio readback.

---

# Challenge 4 Agent Guidelines (Original Reference)

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
