# Additional Data Sources & Integration Guide (Florida — Options 2 & 3)

> **Purpose:** Reference guide for the **Data Lane**, **Agent Lane**, and **Coding Agents** to discover, verify, and integrate supplemental datasets for our two core capabilities:
> - **Option 2 (Custom Tool 1):** *The "Zero-Car Transit Lifeline"* (Carless neighborhoods, Walkability Wall `> 2 km`, bus pre-positioning coordinates, and live routing).
> - **Option 3 (Custom Tool 2):** *The "Generator-Blind Nursing Home Alert"* (Care facilities vs. shelter backup generator gaps, `UNRECORDED` power audit, and pre-season mutual-aid transfer agreements).

---

## 1. Strict License & Compliance Guardrails (Read Before Loading Any Data)

Per challenge rules ([`README.md`](../README.md#bringing-your-own-data)), winning projects are promoted publicly. Every dataset added to BigQuery or `data/` **must** pass these checks:

| Rule | Status | Details |
|---|---|---|
| **US Government / Federal Agencies** | ✅ **SAFE** | Public domain (`17 U.S.C. § 105`). Includes Census/ACS, CDC, CMS, FEMA, HHS, DOT/BTS, NOAA. |
| **State of Florida Public Records** | ✅ **SAFE** | Public records under Chapter 119, Florida Statutes (FDEM, FDOT, Florida AHCA). Check portal metadata to ensure no third-party vendor encumbrance. |
| **CC0 / Public Domain** | ✅ **SAFE** | Unrestricted commercial and derivative use. |
| **OpenStreetMap (ODbL) / CC BY-SA** | ❌ **FORBIDDEN** | **Share-Alike trap:** Do **not** load OSM bus stops, roads, or building footprints. ODbL / CC BY-SA encumbers the entire project. Use US DOT / FDOT public-domain transit data instead. |
| **NonCommercial (NC) / NoDerivatives (ND)** | ❌ **FORBIDDEN** | Automatic disqualification. |
| **Esri Training / Demo Layers on ArcGIS** | ❌ **FORBIDDEN** | Many ArcGIS Online layers (e.g., *"Open Shelters in Harris County"*) are fabricated coursework. Verify the `owner` and `accessInformation` fields belong to an official `.gov` publisher. |
| **Individual-Level Personal Data (PII/PHI)** | ❌ **FORBIDDEN** | Never ingest special-needs shelter sign-up rosters, patient lists, or FEMA `org_poc_*` columns. If a row represents one person, reject it. |
| **Persistent Google Maps Geocoding** | ❌ **FORBIDDEN** | Google Maps Platform ToS forbids caching/storing geocoded `lat`/`lon` in a database beyond 30 days. Only store `place_id` / `review_id`, or use the **US Census Geocoder** (Public Domain) for permanent table coordinates. |
| **Race / Ethnicity Columns (SVI Theme 3)** | ⚠️ **AUDIT ONLY** | Prohibited as a **model/ranking input**. Required for the **post-hoc Equity Audit** to verify our recommendations do not suffer from bureaucratic reporting bias. |

---

## 2. Baseline Tables Already in BigQuery (`<PROJECT>.evacuation_readiness`)

Loaded via [`notebooks/c4_01_load_explore.ipynb`](../notebooks/c4_01_load_explore.ipynb) or `bash scripts/load.sh FL`:

| Table | FL Rows | Key Columns & Schema Notes for Custom Tools |
|---|---:|---|
| `shelters` | 2,793 | `shelter_id`, `shelter_name`, `address_1`, `city`, `county_parish`, `county_fips` (5-char), `county_name`, `state`, `zip`, `latitude`, `longitude`, `evacuation_capacity`, `post_impact_capacity`, `wheelchair_accessible` (**BOOL**), `generator_onsite` (**BOOL**), `self_sufficient_electricity` (**BOOL**), `in_surge_slosh_area` (**BOOL**), `in_100_yr_floodplain` (**BOOL**), `is_medical` (**BOOL**), `is_functional` (**BOOL**), `usage` (`'EVAC'`, `'POST'`, `'BOTH'`). **Note:** `NULL` in boolean columns means **UNRECORDED**, never `FALSE`. |
| `vulnerability_tracts` | 5,160 | `geo_id` (11-char), `county_fips` (5-char, derived from `SUBSTR(geo_id, 1, 5)`), `lat`, `lon`, `total_pop`, `households`, `households_no_vehicle`, `pop_65_plus`, `group_quarters_pop`, `mobile_homes`, `limited_english_spanish`, `median_income`, `poverty_rate`, `pct_disability`, `pct_age_65_plus`, `pct_no_vehicle`, `pct_limited_english`, `pct_mobile_homes`, `pct_group_quarters`, `pct_no_internet`, `svi_socioeconomic`, `svi_household`, `svi_housing_transport`, `pct_mobility`, `pct_selfcare`, `pct_indeplive`, `pct_lacktrpt` (**NULL in FL**). |
| `hazard_tracts` | 5,114 | `geo_id` (11-char), `POPULATION`, `BUILDVALUE`, `HRCN_AFREQ`, `HRCN_EXPP`, `HRCN_EALT`, `HRCN_EALP`, `CFLD_AFREQ`, `CFLD_EXPP`, `CFLD_EALT`, `CFLD_EALP`. |
| `care_facilities` | 694 | `cms_certification_number_ccn` (or `federal_provider_number`), `provider_name`, `provider_address`, `citytown` (or `city`), `state`, `zip_code`, `number_of_certified_beds`, `ownership_type`, `latitude`, `longitude`. **Note:** Has **no** `county_fips` or `county_name` column—must join spatially via `counties` (see Section 3.1). |
| `power_dependent_counties` | 67 | `fips_code` (5-char), `county`, `state`, `power_dependent_dme` (Medicare beneficiaries on electricity-dependent medical equipment), `power_dependent_is_censored` (**BOOL**: `TRUE` when value is `11`, which masks counts of `1–10`). |

---

## 3. Zero-ETL Datasets Already in `bigquery-public-data` (Instant SQL Joins)

These require **no external downloads**—our custom tools and SQL queries can join against them directly inside BigQuery:

### 3.1 US County Boundaries (Essential Bridge Table for Custom Tools 1 & 2)
- **BigQuery Table:** `bigquery-public-data.geo_us_boundaries.counties`
- **License:** US Census Bureau (Public Domain)
- **Key Columns:** `geo_id` (5-digit `county_fips`, e.g., `'12086'` for Miami-Dade), `county_name` (e.g., `'Miami-Dade'`), `state_fips_code` (`'12'` for FL), `county_geom` (`GEOGRAPHY` polygon).
- **Why We Need It:**
  1. `vulnerability_tracts` has `county_fips` but no `county_name`. Joining `counties` on `v.county_fips = c.geo_id` lets users query any Florida county by name.
  2. `care_facilities` has `latitude`/`longitude` but no county column. Joining via `ST_CONTAINS(c.county_geom, ST_GEOGPOINT(cf.longitude, cf.latitude))` assigns every Florida nursing home to its exact county.

### 3.2 ACS 5-Year Tract Demographics (Commute Mode & Post-Hoc Equity Audit)
- **BigQuery Table:** `bigquery-public-data.census_bureau_acs.censustract_2020_5yr` (or newest `censustract_*` table)
- **License:** US Census Bureau (Public Domain)
- **Join Key:** `LPAD(geo_id, 11, '0')` -> matches `vulnerability_tracts.geo_id`
- **Useful Columns for Option 2 (Transit Lifeline):**
  - `commuters_by_public_transportation`, `walked_to_work`, `no_cars`, `one_car`, `two_cars` — distinguishes neighborhoods with active public transit usage vs. complete transit deserts.
- **Useful Columns for Post-Hoc Equity Audit (Never Use as Model Input):**
  - `white_pop`, `black_pop`, `hispanic_pop`, `asian_pop`, `total_pop` — join against the agent's final ranked tracts to audit whether recommendations or `UNRECORDED` shelter gaps disproportionately impact minority communities.

### 3.3 US Census Tract Polygons
- **BigQuery Table:** `bigquery-public-data.geo_census_tracts.us_census_tracts_national`
- **License:** US Census Bureau (Public Domain)
- **Note:** 2010 vintage boundaries (covers 3,338 of 5,160 FL tracts). Useful when polygon geometry (`tract_geom`) is needed in addition to the 2020 NRI centroids in `vulnerability_tracts`.

### 3.4 NOAA Historical Hurricane Tracks
- **BigQuery Table:** `bigquery-public-data.noaa_hurricanes.hurricanes`
- **License:** NOAA / US Government Work (Public Domain)
- **Use Case:** Historical storm tracks (`latitude`, `longitude`, `usa_wind`, `name`, `season`) to contextualize county exposure (e.g., Hurricane Ian 2022, Irma 2017, Michael 2018, Idalia 2023).

---

## 4. High-Value External Datasets for Option 2: "Zero-Car Transit Lifeline"

### 4.1 Seniors Living Alone (`ACS Table B11007`) — Recommended Bonus Signal
- **Why It Matters:** Highlighted in [`README.md`](../README.md#going-further) as *"the best single proxy for 'nobody will notice if they don't leave'"*. Combining `households_no_vehicle` with **65+ living alone** sharpens bus pre-positioning priorities.
- **Publisher & License:** US Census Bureau API — Public Domain.
- **Endpoint (Florida, FIPS `12`):**
  ```text
  https://api.census.gov/data/2022/acs/acs5?get=NAME,B11007_001E,B11007_003E&for=tract:*&in=state:12
  ```
  *(Works without an API key for low-volume pulls; `B11007_003E` = 1-person households aged 65+; `B11007_001E` = total households)*
- **Join Key:** `state + county + tract` (11-character `geo_id`) -> `vulnerability_tracts.geo_id`.

### 4.2 US DOT / BTS National Transit Map Stops (Public Bus Stops for Pickup Coordinates)
- **Why It Matters:** Instead of placing T-minus 48h municipal evacuation buses at arbitrary census tract centroids (which might be in a canal, residential backyard, or cul-de-sac), we can snap pickup coordinates to **actual public transit stops** within the top 5 carless tracts.
- **Publisher & License:** US Department of Transportation (USDOT) / Bureau of Transportation Statistics (BTS) — US Government Work (Public Domain). *(Safe alternative to OpenStreetMap!)*
- **ArcGIS FeatureServer Endpoint:**
  ```text
  https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_National_Transit_Map_Stops/FeatureServer/0/query
  ```
- **Key Fields:** `stop_id`, `stop_name`, `stop_lat`, `stop_lon`, `agency_id`.
- **How to Join:** Spatial join (`ST_DWITHIN(ST_GEOGPOINT(t.lon, t.lat), ST_GEOGPOINT(stop_lon, stop_lat), 1500)`) to pick the central transit stop in each priority tract.

### 4.3 FDOT Official Hurricane Evacuation Routes & Park-and-Ride Lots
- **Why It Matters:** Helps verify whether a carless census tract or proposed bus pickup coordinate sits along a designated state evacuation corridor.
- **Publisher & License:** Florida Department of Transportation (FDOT) Open Data Hub — State of Florida Public Record.
- **Portal / API:** `https://gis-fdot.opendata.arcgis.com/` (Search: *FDOT Emergency Evacuation Routes* / *Park and Ride Lots*).

### 4.4 FDEM Official Florida Storm Surge Evacuation Zones ("Know Your Zone")
- **Why It Matters:** Supplements `shelters.in_surge_slosh_area` by identifying whether a carless census tract itself is inside Evacuation Zone A or B (mandatory first-wave evacuation).
- **Publisher & License:** Florida Division of Emergency Management (FDEM) / Florida Geographic Information Office (`https://geodata.floridagio.gov/`).

---

## 5. High-Value External Datasets for Option 3: "Generator-Blind Nursing Home Alert"

### 5.1 CMS Medicare-Certified Hospitals (`xubh-q36u`) — Mutual-Aid Transfer Receivers
- **Why It Matters:** Option 3 produces a **draft mutual-aid transfer agreement** before September when nearby shelters have `UNRECORDED` or `NO` backup generators. High-acuity nursing home residents often cannot go to a general school shelter—they need a receiving hospital or verified medical facility outside the surge zone.
- **Publisher & License:** Centers for Medicare & Medicaid Services (CMS) — US Government Work (Public Domain).
- **API Endpoint:**
  ```text
  https://data.cms.gov/provider-data/api/1/datastore/query/xubh-q36u/0
  ```
- **Key Fields:** `facility_id`, `facility_name`, `address`, `citytown`, `state` (`'FL'`), `zip_code`, `countyparish`, `hospital_type`, `hospital_ownership`, `emergency_services` (`'Yes'`/`'No'`).
- **Coordinates Note:** CMS Hospitals carry street addresses and county names (`countyparish`) rather than `latitude`/`longitude`. Geocode with the **US Census Batch Geocoder** (Public Domain, below) or ground live at runtime with **Google Maps Grounding**.

### 5.2 CMS Dialysis Facilities (`23ew-n7w9`) — Power-Dependent Outpatient Concentrations
- **Why It Matters:** Directly pairs with `power_dependent_counties` (emPOWER) to locate outpatient renal dialysis centers in the county that require emergency generator power or pre-storm dialysis surge scheduling.
- **Publisher & License:** CMS Provider Data — US Government Work (Public Domain).
- **API Endpoint:**
  ```text
  https://data.cms.gov/provider-data/api/1/datastore/query/23ew-n7w9/0
  ```
- **Key Fields:** `CMS Certification Number (CCN)`, `Facility Name`, `Address Line 1`, `City/Town`, `State` (`'FL'`), `ZIP Code`, `County/Parish`, `Number of Dialysis Stations`.

### 5.3 US Census Bureau Geocoder (Compliant Permanent Geocoding)
- **Why It Matters:** Per [`c4_01_load_explore.ipynb`](../notebooks/c4_01_load_explore.ipynb) Section 9, Google Maps geocoded coordinates cannot be stored in BigQuery tables long-term. The US Census Geocoder is free, public domain, and has no storage restrictions.
- **API Endpoint (Single Address or Batch CSV up to 10,000 rows):**
  - Single: `https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?address=<ADDRESS>&benchmark=Public_AR_Current&format=json`
  - Batch: `https://geocoding.geo.census.gov/geocoder/locations/addressbatch`

### 5.4 Florida AHCA (Agency for Health Care Administration) — Assisted Living Facilities (ALFs) & Nursing Home Emergency Power Plans
- **Why It Matters:**
  1. [`README.md`](../README.md#questions-that-need-more-than-we-gave-you) explicitly calls out Assisted Living Facilities (ALFs) as a major national data gap because ALFs are state-licensed rather than federally listed by CMS.
  2. Following Hurricane Irma, Florida mandated that nursing homes and ALFs maintain 96-hour emergency power/cooling plans tracked by AHCA.
- **Publisher & License:** Florida Agency for Health Care Administration (`FloridaHealthFinder.gov`) — State of Florida Public Record.
- **Portal:** `https://quality.healthfinder.fl.gov/` (Facility/Provider Locator export for Nursing Homes and Assisted Living Facilities).

---

## 6. Live Runtime Grounding & MCP Servers (For the Agent Lane)

Our agent should **never** rely on static tables alone when verifying facility status or computing travel times:

| Source / Tool | How It Is Configured | What It Provides at Runtime |
|---|---|---|
| **Vertex AI Google Maps Grounding (`places` + `routing`)** | `types.Tool(google_maps=types.GoogleMaps(grounding_types=types.GoogleMapsGroundingTypes(places=types.GoogleMapsPlaces(), routing=types.GoogleMapsRouting())))` | 1. **Option 2 (`routing`):** Converts straight-line `ST_DISTANCE` (`> 2 km` Walkability Wall) into actual road drive time and turn-by-turn bus routing.<br>2. **Option 3 (`places`):** Verifies one facility at a time whether a nursing home or shelter is currently open, operational, or renamed.<br>3. **Accessibility Spot-Check:** Queries wheelchair accessibility for specific named buildings (`~5/8` hit rate on single named buildings vs `0` on area queries). |
| **Google Maps Grounding Lite MCP Server** | `https://mapstools.googleapis.com/mcp` (`compute_routes`, `search_places`, `lookup_weather`) | Managed MCP alternative for structured route distance/duration calculations and weather checks. |
| **BigQuery Managed MCP / MCP Toolbox** | Prebuilt BigQuery MCP server | Ad-hoc schema inspection, county rollups, and post-hoc Equity Audit queries. |

---

## 7. Quick Priority Matrix: What to Use First

If time is tight (4.5-hour window), prioritize in this exact order:

1. **Immediate (0 min ETL — SQL only):**
   - Join `bigquery-public-data.geo_us_boundaries.counties` in **Custom Tool 1** and **Custom Tool 2** so both `vulnerability_tracts` and `care_facilities` resolve cleanly by Florida county name (e.g., `"Miami-Dade"`, `"Pinellas"`, `"Lee"`, `"Hillsborough"`).
   - Join `bigquery-public-data.census_bureau_acs.censustract_2020_5yr` for public transit commute share and the **Post-Hoc Equity Audit** tool.
2. **High-ROI Fast Pull (~5 min Python script):**
   - Pull **ACS `B11007_003E` (Seniors 65+ Living Alone)** for Florida tracts (1 HTTP GET request for all 5,160 FL tracts) and join to `vulnerability_tracts` for **Option 2**.
   - Pull **CMS Hospitals (`xubh-q36u`)** for Florida (~215 rows, 1 HTTP GET request) so **Option 3** can name real local receiving hospitals in its draft mutual-aid transfer agreements.
3. **Runtime Differentiator (Built into Agent):**
   - Use **Google Maps Grounding (`places` + `routing`)** on the top 5 carless tracts (Option 2) and top at-risk nursing homes (Option 3), displaying `<span translate="no">Google Maps</span>` source links immediately after grounded claims.
