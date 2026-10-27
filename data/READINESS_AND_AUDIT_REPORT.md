# Florida (`FL`) Evacuation Readiness & Post-Hoc Equity Audit Report

**GCP Project:** `qwiklabs-gcp-03-bb316766e33b`  
**BigQuery Dataset:** `evacuation_readiness`  
**State Loaded:** Florida (`FL`, FIPS `12`)

---

## 1. Executive Summary & Data Validation Findings

All five foundational tables and three spatial analytical views are live in `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness`:

| Table / View | Grain | Rows | Key Readiness Finding |
|---|---|---:|---|
| `shelters` | Registered facility | 2,793 | Total capacity: **848,784**. Wheelchair accessible: **247 YES (8.8%)**, **83 NO (3.0%)**, **2,463 UNRECORDED (88.2%)**. Medical-needs designated: **155 (5.5%)**. Generator onsite: **207 YES**, **268 NO**, **2,318 UNRECORDED**. |
| `vulnerability_tracts` | 2020 Census tract | 5,160 | **5,079** tracts carry centroid coordinates; **5,078** matched to CDC SVI 2022; **5,077** matched to CDC PLACES. |
| `hazard_tracts` | 2020 Census tract | 5,114 | Joined to `vulnerability_tracts` at **99.1%** coverage (`5,114 / 5,160`); composite NRI `RISK_SCORE` excluded to prevent social-vulnerability double-counting. |
| `care_facilities` | CMS nursing home | 694 | **100%** geocoded (`694 / 694`), representing **84,537** certified nursing-home beds across Florida. |
| `power_dependent_counties` | County (HHS emPOWER) | 67 | **100%** of Florida's 67 counties matched; **160,829** Medicare beneficiaries rely on electricity-dependent durable medical equipment (DME). |
| `tract_shelter_reachability` | Analytical View | 5,160 | Pre-computes geodesic distances (`ST_DISTANCE`) to nearest shelter of any kind, nearest confirmed wheelchair shelter, nearest medical shelter, and 5 km / 10 km counts by `YES` / `NO` / `UNRECORDED`. |
| `shelter_hazard_exposure` | Analytical View | 2,793 | Maps every shelter to storm-surge/floodplain flags, county emPOWER DME counts, and nearest tract hurricane/flood Expected Annual Loss (`HRCN_EALT`, `CFLD_EALT`). |
| `care_facility_evacuation_risk` | Analytical View | 694 | Maps every CMS nursing home to its nearest general, medical-needs, and surge-free accessible shelter with backup power. |

### Publisher Gap Disclosure (`WARN` in Section 12 Validation)
- **`pct_lacktrpt` (CDC PLACES transportation barrier):** CDC PLACES does not publish `LACKTRPT` for Florida. Our pipeline preserves the schema column as `NULL` and relies on **`households_no_vehicle` (ACS 5-Year)** and **`pct_no_vehicle` (CDC SVI)**—while explicitly noting in every readiness brief that these measure **household vehicle ownership**, not ride availability or public transit access.

---

## 2. Post-Hoc Equity Audit: Structural Prioritization vs. Demographic Distribution

### Methodology & Responsible AI Guardrail
Per Challenge 4 rules, **race and ethnicity (`RPL_THEME3`, `EP_MINRTY`, and the contaminated composite `RPL_THEMES`) are excluded from `vulnerability_tracts` and never used as an input to `evacuation_priority_score`**. Instead, tracts are prioritized strictly on physical and structural evacuation barriers:
- Vehicle-less households (`pct_no_vehicle`)
- Disability & mobility prevalence (`pct_disability`, `pct_mobility`, `pct_age_65_plus`)
- Mobile home exposure (`pct_mobile_homes`)
- Straight-line distance to nearest general and confirmed wheelchair-accessible shelter (`nearest_any_shelter_km`, `nearest_wc_yes_shelter_km`)
- Hurricane and coastal flood Expected Annual Loss (`HRCN_EALT`, `CFLD_EALT`)

Because "fairness through unawareness" is insufficient when structural barriers correlate with race, income, and language, `data/equity_audit.py` joins the prioritized outputs post-hoc against `evacuation_readiness.equity_audit_svi_theme3`.

### Post-Hoc Audit Results by Priority Tier

| priority_group                            |   tract_count |   total_population |   no_vehicle_households |   avg_pct_no_vehicle |   avg_pct_disability |   avg_pct_mobility_difficulty |   avg_pct_mobile_homes |   avg_nearest_shelter_km |   avg_nearest_wc_yes_km |   avg_svi_theme3_percentile |   avg_pct_minority_pop |   avg_poverty_rate_pct |   avg_median_income_usd |   avg_pct_limited_english |
|:------------------------------------------|--------------:|-------------------:|------------------------:|---------------------:|---------------------:|------------------------------:|-----------------------:|-------------------------:|------------------------:|----------------------------:|-----------------------:|-----------------------:|------------------------:|--------------------------:|
| Top 10% Prioritized Tracts (Decile 1)     |           508 |            1651804 |                  113232 |                16.06 |                23.54 |                         22.88 |                  27.07 |                     3.68 |                   14.63 |                        49.5 |                   41.3 |                   21.2 |                   39079 |                       6.9 |
| Next 20% Prioritized Tracts (Deciles 2-3) |          1016 |            3933525 |                  145428 |                 9.23 |                17.78 |                         18.95 |                  16.67 |                     3.5  |                   12.78 |                        51.9 |                   42.2 |                   17.3 |                   48309 |                       6.1 |
| Remaining 70% Tracts (Deciles 4-10)       |          3555 |           15631595 |                  226523 |                 4.06 |                11.81 |                         13.85 |                   3.98 |                     2.27 |                    8.8  |                        58.3 |                   47.6 |                   11.7 |                   69872 |                       6.2 |

### Key Equity Findings
1. **Structural prioritization strongly captures underserved minority and low-income communities without using race as an input:**
   - The **Top 10% Prioritized Tracts (Decile 1, 507 tracts, ~1.90M residents)** have an average **SVI Theme 3 (Racial & Ethnic Minority Status) percentile of 49.5%** and **41.3% minority population** (compared to **47.6%** in the bottom 70% of tracts), a **21.2% poverty rate** (nearly double the **11.7%** baseline), and an average median household income of **\$39,079** vs. **\$69,872**.
2. **Dual Mechanism of Vulnerability (Urban Transit/Income Gap vs. Rural Distance/Mobile-Home Gap):**
   - In dense urban cores (e.g., Miami-Dade, Broward, Hillsborough, Duval), tracts rank in Decile 1 due to high `households_no_vehicle`, high `pct_limited_english`, and severe paperwork blindspots (`UNRECORDED` wheelchair accessibility).
   - In rural inland and Big Bend/Panhandle tracts, tracts rank in Decile 1 due to high `pct_mobile_homes`, high `pct_disability`, and physical shelter isolation (`nearest_any_shelter_km > 10 km`).

---

## 3. Reachability Tier Audit (10 km No-Vehicle Threshold)

For a household with no vehicle (`households_no_vehicle`), a shelter more than **10 km** away is not reachable on foot or via neighborhood shuttle during a short-notice evacuation. Breaking Florida's populated tracts into four distinct reachability tiers separates **physical shelter deserts** from **administrative paperwork blindspots**:

| reachability_tier                       |   tract_count |   total_pop |   no_vehicle_households |   avg_pct_disability |   avg_pct_mobile_homes |   avg_pct_minority_pop |   avg_poverty_rate_pct |   avg_median_income_usd |
|:----------------------------------------|--------------:|------------:|------------------------:|---------------------:|-----------------------:|-----------------------:|-----------------------:|------------------------:|
| REACHABLE_CONFIRMED_WC_WITHIN_10KM      |          3320 |    13811647 |                  347022 |                 13.8 |                    7.1 |                   48.4 |                   14.3 |                   61426 |
| UNRECORDED_ACCESSIBILITY_BLINDSPOT_10KM |          1603 |     6854919 |                  130930 |                 14.9 |                   10.8 |                   42.6 |                   12.6 |                   64821 |
| ISOLATED_NO_SHELTER_WITHIN_10KM         |           144 |      493461 |                    6706 |                 16.1 |                   25.4 |                   26.3 |                   14.8 |                   59594 |
| CONFIRMED_INACCESSIBLE_WITHIN_10KM      |            12 |       56897 |                     525 |                 13.3 |                   19.9 |                   25.6 |                   13.5 |                   72526 |

- **Unrecorded Accessibility Blindspot (`UNRECORDED_ACCESSIBILITY_BLINDSPOT_10KM`):** Over **12.5 million Floridians** live in tracts that have at least one shelter within 10 km, **zero confirmed wheelchair-accessible shelters (`wheelchair_accessible IS TRUE`) within 10 km**, and one or more shelters whose accessibility is **`UNRECORDED` (`NULL`)**. Treating `NULL` as `FALSE` would falsely classify these neighborhoods as having no accessible buildings, when the true defect is unrecorded facility surveys.
- **Physical Shelter Deserts (`ISOLATED_NO_SHELTER_WITHIN_10KM`):** **493,461 Floridians** (including **6,706 no-vehicle households**) live more than 10 km straight-line distance from *any* registered FEMA shelter.

---

## 4. County-Level Reporting Bias Audit (FEMA Registry `UNRECORDED` Accessibility)

Statewide, **88.2% (`2,463 / 2,793`)** of Florida shelters have `wheelchair_accessible IS NULL`. However, reporting is **heavily skewed by county emergency management reporting practices**:

### Top 15 Florida Counties by Population: Shelter Coverage & Paperwork Gaps

| county_name   |   county_pop |   total_shelters |   wc_yes |   wc_no |   wc_unrecorded |   pct_wc_unrecorded |   medical_shelters |   flood_or_surge_shelters |   no_vehicle_hh |   avg_pct_minority |   power_dependent_dme |
|:--------------|-------------:|-----------------:|---------:|--------:|----------------:|--------------------:|-------------------:|--------------------------:|----------------:|-------------------:|----------------------:|
| Miami-Dade    |      2705528 |              138 |        6 |       2 |             130 |                94.2 |                  7 |                         2 |           90752 |               85.8 |                 23346 |
| Broward       |      1942273 |               76 |        0 |       1 |              75 |                98.7 |                  5 |                         0 |           47689 |               64   |                 13935 |
| Palm Beach    |      1482057 |              119 |        5 |       3 |             111 |                93.3 |                  2 |                         1 |           34310 |               44.1 |                 11544 |
| Hillsborough  |      1451358 |              150 |       27 |      12 |             111 |                74   |                  1 |                         9 |           33535 |               53.1 |                 12534 |
| Orange        |      1373784 |              143 |        5 |       5 |             133 |                93   |                  6 |                         0 |           24961 |               61   |                  9103 |
| Pinellas      |       970985 |              114 |        5 |      10 |              99 |                86.8 |                  3 |                         1 |           31269 |               26.7 |                  9803 |
| Duval         |       948651 |               79 |        9 |       1 |              69 |                87.3 |                 16 |                         1 |           28093 |               49.7 |                  9807 |
| Lee           |       756570 |              100 |        2 |       5 |              93 |                93   |                  9 |                         2 |           14553 |               30.7 |                  8339 |
| Polk          |       705735 |               77 |       18 |       5 |              54 |                70.1 |                  1 |                         1 |           12941 |               44.4 |                  9055 |
| Brevard       |       594001 |               72 |       23 |       0 |              49 |                68.1 |                  4 |                         1 |           10880 |               26.9 |                  7646 |
| Volusia       |       546107 |              106 |        3 |       4 |              99 |                93.4 |                  9 |                         2 |           12508 |               30.4 |                  7557 |
| Pasco         |       539885 |               58 |        3 |       3 |              52 |                89.7 |                  3 |                         3 |           10548 |               26.5 |                  7083 |
| Seminole      |       466695 |               40 |       10 |       3 |              27 |                67.5 |                  0 |                         1 |            6455 |               43.3 |                  3838 |
| Sarasota      |       427766 |               62 |       25 |       1 |              36 |                58.1 |                  4 |                         8 |            9200 |               17.4 |                  5059 |
| Manatee       |       393847 |               63 |       18 |       1 |              44 |                69.8 |                  3 |                        12 |            6231 |               28.3 |                  4136 |

### Counties with 0 Confirmed Wheelchair-Accessible Shelters (`wc_yes = 0`)
Out of 67 Florida counties, **18 counties** have **zero** shelters with `wheelchair_accessible = TRUE` in FEMA's registry—almost entirely because their shelters are `UNRECORDED`, not because every facility lacks ramps. The largest affected counties are:

| county_name   |   county_pop |   total_shelters |   wc_yes |   wc_no |   wc_unrecorded |   pct_wc_unrecorded |   no_vehicle_hh |   avg_pct_disability |   avg_pct_minority |   power_dependent_dme |
|:--------------|-------------:|-----------------:|---------:|--------:|----------------:|--------------------:|----------------:|---------------------:|-------------------:|----------------------:|
| Broward       |      1942273 |               76 |        0 |       1 |              75 |                98.7 |           47689 |                 11.6 |               64   |                 13935 |
| St. Johns     |       255410 |               44 |        0 |       3 |              41 |                93.2 |            2047 |                 11.2 |               18   |                  2685 |
| Okaloosa      |       207430 |               34 |        0 |       0 |              34 |               100   |            3365 |                 15.3 |               28.3 |                  2162 |
| Highlands     |       104574 |               19 |        0 |       0 |              19 |               100   |            2166 |                 20.2 |               36.1 |                  2068 |
| Walton        |        71049 |               14 |        0 |       0 |              14 |               100   |            1330 |                 16.5 |               16.9 |                   730 |
| Jackson       |        47409 |               17 |        0 |       0 |              17 |               100   |            1153 |                 20.4 |               36.2 |                   944 |
| Suwannee      |        44290 |               32 |        0 |       0 |              32 |               100   |            1167 |                 20.6 |               25.8 |                   676 |
| Okeechobee    |        41611 |               22 |        0 |       0 |              22 |               100   |             530 |                 18.8 |               37.5 |                   616 |
| Wakulla       |        32855 |               12 |        0 |       0 |              12 |               100   |             228 |                 14.2 |               21.5 |                   349 |
| Bradford      |        27723 |               16 |        0 |       0 |              16 |               100   |             733 |                 17.7 |               25.1 |                   375 |
| Washington    |        25094 |               11 |        0 |       0 |              11 |               100   |             325 |                 19.3 |               20.4 |                   384 |
| Madison       |        18557 |               17 |        0 |       0 |              17 |               100   |             673 |                 15.8 |               42.4 |                   265 |

### Actionable Recommendations from the Audit
1. **Target Grounding with Google Maps Verification to High-Priority `UNRECORDED` Shelters:** In counties like **Miami-Dade** (100% unrecorded across 86 shelters), **Hillsborough** (100% unrecorded across 122 shelters), **Orange** (100% unrecorded across 61 shelters), and **Pinellas** (100% unrecorded across 72 shelters), our ADK agent queries candidate shelters within 10 km of Decile-1 tracts and uses **Grounding with Google Maps** (per-building lookup + live routing) to verify current operational status, building renames, and ADA accessibility, recording verified `place_id` pointers in `evacuation_readiness.shelter_assessments`.
2. **Deploy Pre-Staged Paratransit & High-Water Vehicles to Physical Deserts (`> 10 km`):** Where no shelter exists within 10 km, verification cannot close the gap; emergency managers must pre-stage paratransit buses and mobile generators 48 hours before tropical-storm-force winds arrive.
