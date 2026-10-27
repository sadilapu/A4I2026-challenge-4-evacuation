# data/

**This folder is empty, and that is the design.**

Everything this challenge uses is pulled live from its original publisher by
`notebooks/c4_01_load_explore.ipynb` and loaded straight into BigQuery in **your** project. Nothing
is pre-cleaned and handed to you, because the cleaning decisions *are* the teaching—a shipped
table would hide six real defects in federal data that you should see happen.

If a publisher is having a bad morning, `bash scripts/load.sh <STATE>` rebuilds the identical tables
from a Cloud Storage snapshot instead.

## Where the data actually lives

After the notebook or `load.sh` runs, in `<your-project>.evacuation_readiness`:

| Table | Grain | What it holds |
|---|---|---|
| `shelters` | one row per registered facility | capacity, wheelchair access, generator, surge and floodplain exposure, medical-needs designation, county |
| `vulnerability_tracts` | one row per census tract | no-vehicle households, 65+, disability, limited English, group quarters, mobile homes, coordinates |
| `hazard_tracts` | one row per census tract | hurricane and coastal-flood exposure and expected annual loss |
| `care_facilities` | one row per nursing home | coordinates and certified bed count |
| `power_dependent_counties` | one row per county | Medicare beneficiaries relying on electricity for medical equipment |

## If you add your own data

You may, and it earns credit—but the license rules on the challenge card apply to anything you
bring, and they are not a formality. A winning project gets promoted publicly, so an unchecked
share-alike or non-commercial source becomes somebody else's legal problem.

Put small reference files here and commit them. Anything large, or anything pulled live, belongs in
BigQuery rather than in git.


---

## Implemented Data Lane Deliverables (`FL` in `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness`)

1. **[`readiness_queries.sql`](./readiness_queries.sql)**:
   - **`shelter_hazard_exposure` (View, 2,793 rows):** Enriches every Florida shelter with explicit 3-state accessibility (`YES` / `NO` / `UNRECORDED`) and generator (`YES` / `NO` / `UNRECORDED`) status, storm-surge (`in_surge_slosh_area`) and 100-year floodplain (`in_100_yr_floodplain`) flags, county Medicare power-dependent DME counts (`power_dependent_dme`), and nearest tract hurricane/coastal-flood Expected Annual Loss (`HRCN_EALT`, `CFLD_EALT`).
   - **`tract_shelter_reachability` (View, 5,160 rows):** Computes geodesic straight-line distances (`ST_DISTANCE`) from every census tract centroid to the nearest shelter of any kind, nearest confirmed wheelchair-accessible shelter (`wheelchair_accessible IS TRUE`), nearest medical-needs shelter (`is_medical IS TRUE`), and nearest surge-free generator shelter; counts shelters within `5 km` and `10 km` broken out by `YES`, `NO`, and `UNRECORDED`; classifies tracts into four 10 km reachability tiers; and computes `evacuation_priority_score` strictly from physical/structural barriers (excluding SVI Theme 3 / race & ethnicity).
   - **`care_facility_evacuation_risk` (View, 694 rows):** Maps every CMS-certified nursing home in Florida (`84,537` beds) to its nearest general, medical-needs, and surge-free accessible shelter with backup power.
   - **`shelter_assessments` (Table):** Operational write-back table storing verified accessibility assessments and exempt `Google Maps` `place_id` / `review_id` pointers (never caching raw Google Maps content).
2. **[`equity_audit.py`](./equity_audit.py) & [`READINESS_AND_AUDIT_REPORT.md`](./READINESS_AND_AUDIT_REPORT.md)**:
   - Loads CDC SVI Theme 3 (`RPL_THEME3`, `EP_MINRTY`) into a separate post-hoc audit table (`evacuation_readiness.equity_audit_svi_theme3`) and audits how structural prioritization and County `UNRECORDED` accessibility paperwork blindspots intersect with minority, low-income, and limited-English communities across all 67 Florida counties.
