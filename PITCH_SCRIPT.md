# EvacPulse AI — 3-Minute Executive Pitch & Demo Script (Challenge 4)

**Live App**: [https://evacuation-readiness-agent-360663039447.us-central1.run.app](https://evacuation-readiness-agent-360663039447.us-central1.run.app)  
**Speaking Time**: ~2 minutes 15 seconds (~280 words, leaving 45s buffer for live clicks)

---

## 1. Intro — The Human Stakes (0:00 – 0:25)
**[ON SCREEN: Open EvacPulse AI Dashboard]**
> "When a hurricane hits, people with cars drive inland. Those who die are the ones who cannot: families without a vehicle, seniors in wheelchairs, and patients on electric oxygen or dialysis. After Hurricane Ian, the median age of fatalities was in the seventies.
>
> Those residents are findable months in advance in public federal data. We built **EvacPulse AI**: an adaptive readiness agent for **all 67 Florida counties** that helps emergency managers and hospitals fix shelter, transit, and power gaps in **August—weeks before a storm forms**."

---

## 2. The Challenge — Four Federal Data Blind Spots (0:25 – 0:55)
**[ON SCREEN: Point to the 4 Hero KPI Cards]**
> "Auditing the five federal datasets in BigQuery revealed four critical traps:
> 1. **`UNRECORDED` does not mean `NO`**: **88%** of Florida's 2,793 FEMA shelters have `NULL` (unrecorded) wheelchair access. Treating `NULL` as 'No' discards 90% of capacity; treating it as 'Yes' endangers wheelchair users.
> 2. **Stale 2022 Registries & Surge Risk**: Static files cannot tell if a building closed, changed its name, or sits in a coastal storm-surge (`SLOSH`) flood zone.
> 3. **Straight-Line vs. Street Drive Time**: BigQuery `ST_DISTANCE` measures straight lines, not real road travel times across bridges to stage buses 48 hours early.
> 4. **Reporting Bias & Scale Gaps**: Our equity audit proves high-vulnerability tracts (`SVI >= 0.75`) have higher rates of unrecorded shelter data, while HHS emPOWER tracks power-dependent patients only at the county level."

---

## 3. Solution & Live Demo Features (0:55 – 1:55)
**[ON SCREEN: Switch County Dropdown → Tap Mic → Click Map Overlays → Click Verify on Google Maps]**
> "Here is how **EvacPulse AI** solves all four in a plain-English, non-technical workspace:
> - **Dynamic 67-County & Voice Briefing**: Switching the dropdown to any Florida county runs all four BigQuery spatial audits in parallel, silently updating the dashboard. Only when I tap the **Microphone** and ask a question by voice does **Gemini 2.5 Flash TTS (`Kore`)** read back a natural, paraphrased briefing—with instant **Stop** and **Replay** controls.
> - **Role-Adaptive Views & In-Map Overlays**:
>   - **Local Emergency Planner View** overlays amber pins for unrecorded high-capacity shelters, red circles for storm-surge danger zones, and cyan dashed lines for 48-hour bus pickup routes from zero-car neighborhoods.
>   - **Hospital & Nursing Home View** maps CMS nursing homes, county emPOWER electricity-dependent patients, and 10 km transfer routes to confirmed generator shelters.
> - **Live Grounding with Google Maps & Routing**: Clicking **'Verify on Google Maps'** on a facility like *Page Rehabilitation* calls **Vertex AI Grounding with Google Maps** live—catching that it renamed to *Calusa Harbour*, checking live wheelchair entrance details, and comparing real street drive time against straight-line distance.
> - **Live BigQuery Write-Back**: Clicking **'Save Inspection Result'** writes verified wheelchair and generator status straight back to BigQuery's `shelter_assessments` table."

---

## 4. Architecture Overview (1:55 – 2:20)
**[ON SCREEN: Point to Grounded Agent Card & Google Maps Attribution (`translate="no"`)]**
> "**EvacPulse AI** is deployed on **Google Cloud Run** using **Google ADK (`google-adk`)**:
> - A **Gemini Root Agent** orchestrates four parallel **BigQuery Spatial SQL** tools (`ST_DISTANCE`, `ST_GEOGPOINT`) and **Google's Managed BigQuery MCP Server (`McpToolset`)**.
> - A dedicated **Maps Grounding Sub-Agent (`AgentTool`)** executes live **Grounding with Google Maps** (`places` + `routing`) with compliant `Google Maps` attribution.
> - **Gemini 2.5 Flash Multimodal Audio & Native TTS** power voice search and natural spoken readback."

---

## 5. Conclusion Statement (2:20 – 2:35)
**[ON SCREEN: Full Map & Action Checklist]**
> "Our BigQuery data is the memory; **Google Maps** is the eyes. **EvacPulse AI** never confuses missing paperwork with missing buildings—it finds who needs help, verifies what is on the ground today, and closes life-saving gaps before the storm hits. Thank you!"
