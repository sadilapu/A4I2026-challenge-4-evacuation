"""
Custom BigQuery & Spatial Decision Tools for the Florida Evacuation Readiness Agent.

Enforces all Challenge 4 data and Responsible AI rules:
- Never collapses NULL (`UNRECORDED`) wheelchair or generator flags into `FALSE`.
- Distinguishes straight-line geodesic distance (`ST_DISTANCE` in BigQuery) from
  driving route distance/time returned live by Grounding with Google Maps.
- Discloses that CDC PLACES `pct_lacktrpt` is NULL in Florida and uses ACS
  `households_no_vehicle` + CDC SVI `pct_no_vehicle` (vehicle ownership).
- Excludes race/ethnicity (`RPL_THEME3`, `EP_MINRTY`) from prioritization inputs
  and uses them strictly in `run_posthoc_equity_audit`.
- Stores only `google_maps_place_id` and `google_maps_review_id` pointers (never
  cached Google Maps content) in `evacuation_readiness.shelter_assessments`.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any
from google.cloud import bigquery

PROJECT_ID = "qwiklabs-gcp-03-bb316766e33b"
DATASET_ID = "evacuation_readiness"

_bq_client: bigquery.Client | None = None


def _get_bq() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def get_vulnerable_tracts(
    county_name: str = "",
    limit: int = 8,
    only_unrecorded_or_isolated_10km: bool = False,
) -> dict[str, Any]:
    """Rank census tracts in Florida (or a specific county) by structural evacuation vulnerability and shelter distance.

    Args:
        county_name: Optional Florida county name (e.g. 'Miami-Dade', 'Hillsborough', 'Pinellas', 'Lee', 'Broward'). Leave empty for statewide top tracts.
        limit: Number of highest-priority census tracts to return (default 8, max 25).
        only_unrecorded_or_isolated_10km: If True, filter to tracts that have ZERO confirmed wheelchair-accessible shelters within 10 km.

    Returns:
        Dictionary with county/state summary metrics, publisher data notes, and ranked census tracts with coordinates and shelter reachability counts (YES vs NO vs UNRECORDED).
    """
    bq = _get_bq()
    limit = max(1, min(int(limit), 25))
    where_clauses = ["total_pop > 100", "lat IS NOT NULL"]
    params = []

    if county_name and county_name.strip():
        clean_county = county_name.strip().replace(" County", "").replace(" county", "")
        where_clauses.append("LOWER(county_name) LIKE LOWER(@county_pattern)")
        params.append(bigquery.ScalarQueryParameter("county_pattern", "STRING", f"%{clean_county}%"))

    if only_unrecorded_or_isolated_10km:
        where_clauses.append("COALESCE(shelters_within_10km_wc_yes, 0) = 0")

    where_sql = " AND ".join(where_clauses)

    query = f"""
    SELECT
      geo_id,
      county_name,
      county_fips,
      ROUND(lat, 5) AS tract_lat,
      ROUND(lon, 5) AS tract_lon,
      CAST(total_pop AS INT64) AS total_pop,
      CAST(households AS INT64) AS households,
      CAST(households_no_vehicle AS INT64) AS households_no_vehicle,
      ROUND(pct_no_vehicle, 1) AS pct_no_vehicle_ownership,
      ROUND(pct_disability, 1) AS pct_disability,
      ROUND(pct_mobility, 1) AS pct_mobility_difficulty,
      ROUND(pct_selfcare, 1) AS pct_selfcare_difficulty,
      ROUND(pct_indeplive, 1) AS pct_independent_living_difficulty,
      ROUND(pct_age_65_plus, 1) AS pct_age_65_plus,
      ROUND(pct_mobile_homes, 1) AS pct_mobile_homes,
      ROUND(pct_limited_english, 1) AS pct_limited_english,
      ROUND(poverty_rate, 1) AS poverty_rate_pct,
      CAST(median_income AS INT64) AS median_income_usd,
      ROUND(hurricane_expected_annual_loss, 0) AS hurricane_expected_annual_loss_usd,
      ROUND(coastal_flood_expected_annual_loss, 0) AS coastal_flood_expected_annual_loss_usd,
      nearest_any_shelter_km,
      nearest_any_shelter_id,
      nearest_any_shelter_name,
      nearest_any_shelter_address,
      nearest_any_shelter_city,
      nearest_any_shelter_wc_status,
      nearest_wc_yes_shelter_km,
      nearest_wc_yes_shelter_id,
      nearest_wc_yes_shelter_name,
      nearest_wc_yes_shelter_address,
      nearest_wc_yes_shelter_city,
      nearest_medical_shelter_km,
      nearest_medical_shelter_name,
      nearest_resilient_shelter_km,
      shelters_within_5km_total,
      shelters_within_5km_wc_yes,
      shelters_within_5km_wc_no,
      shelters_within_5km_wc_unrecorded,
      shelters_within_10km_total,
      shelters_within_10km_wc_yes,
      shelters_within_10km_wc_no,
      shelters_within_10km_wc_unrecorded,
      CAST(capacity_within_10km AS INT64) AS capacity_within_10km,
      reachability_tier,
      evacuation_priority_score
    FROM `{PROJECT_ID}.{DATASET_ID}.tract_shelter_reachability`
    WHERE {where_sql}
    ORDER BY evacuation_priority_score DESC
    LIMIT {limit}
    """

    job_config = bigquery.QueryJobConfig(query_parameters=params)
    rows = [dict(r) for r in bq.query(query, job_config=job_config).result()]

    # Also compute aggregate stats for the selected scope
    summary_query = f"""
    SELECT
      COUNT(*) AS total_tracts_in_scope,
      CAST(SUM(total_pop) AS INT64) AS total_pop_in_scope,
      CAST(SUM(households_no_vehicle) AS INT64) AS total_no_vehicle_households,
      COUNTIF(nearest_any_shelter_km > 10.0) AS tracts_over_10km_from_any_shelter,
      CAST(SUM(IF(nearest_any_shelter_km > 10.0, total_pop, 0)) AS INT64) AS pop_over_10km_from_any_shelter,
      COUNTIF(nearest_wc_yes_shelter_km > 10.0 OR nearest_wc_yes_shelter_km IS NULL) AS tracts_over_10km_from_confirmed_wc_shelter,
      CAST(SUM(IF(nearest_wc_yes_shelter_km > 10.0 OR nearest_wc_yes_shelter_km IS NULL, total_pop, 0)) AS INT64) AS pop_over_10km_from_confirmed_wc_shelter,
      COUNTIF(reachability_tier = 'UNRECORDED_ACCESSIBILITY_BLINDSPOT_10KM') AS tracts_in_unrecorded_blindspot_10km
    FROM `{PROJECT_ID}.{DATASET_ID}.tract_shelter_reachability`
    WHERE {where_sql}
    """
    summary = dict(list(bq.query(summary_query, job_config=job_config).result())[0])

    return {
        "scope": county_name or "Statewide (Florida)",
        "distance_methodology": (
            "All BigQuery distances (`nearest_any_shelter_km`, `nearest_wc_yes_shelter_km`) are "
            "straight-line geodesic distances (`ST_DISTANCE`). Use Grounding with Google Maps "
            "(with routing) on candidate shelters to obtain live driving distance and drive time."
        ),
        "publisher_data_note": (
            "CDC PLACES does not publish `pct_lacktrpt` (transportation barrier) for Florida (column is NULL). "
            "Vehicle access is measured via ACS `households_no_vehicle` and CDC SVI `pct_no_vehicle`, which "
            "measure household vehicle ownership rather than ride availability."
        ),
        "responsible_ai_note": (
            "SVI Theme 3 (Racial & Ethnic Minority Status) and composite RPL_THEMES / NRI RISK_SCORE are "
            "excluded from `evacuation_priority_score` inputs. Call `run_posthoc_equity_audit` to audit "
            "demographic impacts post-hoc."
        ),
        "scope_summary": summary,
        "prioritized_tracts": rows,
    }


def evaluate_county_shelters(
    county_name: str,
    near_lat: float = 0.0,
    near_lon: float = 0.0,
    radius_km: float = 15.0,
    exclude_surge_and_floodplain: bool = False,
    limit: int = 12,
) -> dict[str, Any]:
    """Evaluate shelter coverage, accessibility paperwork gaps (YES vs NO vs UNRECORDED), generator status, and hazard exposure in a county or around a coordinate.

    Args:
        county_name: Florida county name (e.g. 'Miami-Dade', 'Hillsborough', 'Pinellas', 'Lee').
        near_lat: Optional latitude of a vulnerable census tract or nursing home to sort candidate shelters by proximity.
        near_lon: Optional longitude of a vulnerable census tract or nursing home to sort candidate shelters by proximity.
        radius_km: Maximum straight-line distance in km when `near_lat` and `near_lon` are provided (default 15.0 km).
        exclude_surge_and_floodplain: If True, exclude shelters flagged in `in_surge_slosh_area` or `in_100_yr_floodplain`.
        limit: Maximum number of candidate shelter records to return for live Google Maps verification (default 12, max 25).

    Returns:
        Dictionary containing a 3-state accessibility/generator breakdown (`YES`, `NO`, `UNRECORDED`), hazard exposure summary, and candidate shelter rows with exact name + street address for per-building Google Maps grounding.
    """
    bq = _get_bq()
    limit = max(1, min(int(limit), 25))
    clean_county = county_name.strip().replace(" County", "").replace(" county", "")

    params = [
        bigquery.ScalarQueryParameter("county_pattern", "STRING", f"%{clean_county}%"),
    ]

    summary_sql = f"""
    SELECT
      ANY_VALUE(county_name) AS county_name,
      ANY_VALUE(county_fips) AS county_fips,
      COUNT(*) AS total_shelters,
      CAST(SUM(evacuation_capacity) AS INT64) AS total_evacuation_capacity,
      CAST(SUM(post_impact_capacity) AS INT64) AS total_post_impact_capacity,
      COUNTIF(wheelchair_status = 'YES') AS wheelchair_yes,
      COUNTIF(wheelchair_status = 'NO') AS wheelchair_no,
      COUNTIF(wheelchair_status = 'UNRECORDED') AS wheelchair_unrecorded,
      ROUND(100.0 * COUNTIF(wheelchair_status = 'UNRECORDED') / GREATEST(COUNT(*), 1), 1) AS pct_wheelchair_unrecorded,
      COUNTIF(generator_status = 'YES') AS generator_yes,
      COUNTIF(generator_status = 'NO') AS generator_no,
      COUNTIF(generator_status = 'UNRECORDED') AS generator_unrecorded,
      COUNTIF(is_medical IS TRUE) AS medical_needs_shelters,
      COUNTIF(in_surge_slosh_area IS TRUE) AS in_storm_surge_slosh_area,
      COUNTIF(in_100_yr_floodplain IS TRUE) AS in_100_yr_floodplain,
      COUNTIF(has_flood_or_surge_flag IS FALSE AND generator_status = 'YES' AND wheelchair_status = 'YES') AS confirmed_resilient_accessible_shelters,
      CAST(ANY_VALUE(county_power_dependent_dme) AS INT64) AS county_power_dependent_medicare_dme
    FROM `{PROJECT_ID}.{DATASET_ID}.shelter_hazard_exposure`
    WHERE LOWER(county_name) LIKE LOWER(@county_pattern)
    """
    summary_rows = list(bq.query(summary_sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
    summary = dict(summary_rows[0]) if summary_rows else {}

    has_coords = abs(near_lat) > 0.001 and abs(near_lon) > 0.001
    if has_coords:
        params.extend(
            [
                bigquery.ScalarQueryParameter("near_lat", "FLOAT64", float(near_lat)),
                bigquery.ScalarQueryParameter("near_lon", "FLOAT64", float(near_lon)),
                bigquery.ScalarQueryParameter("radius_km", "FLOAT64", float(radius_km)),
            ]
        )
        dist_expr = "ROUND(ST_DISTANCE(ST_GEOGPOINT(longitude, latitude), ST_GEOGPOINT(@near_lon, @near_lat)) / 1000.0, 2)"
        dist_filter = f"AND {dist_expr} <= @radius_km"
        order_by = "straight_line_dist_km ASC, evacuation_capacity DESC"
    else:
        dist_expr = "CAST(NULL AS FLOAT64)"
        dist_filter = ""
        order_by = "evacuation_capacity DESC, shelter_name ASC"

    hazard_filter = "AND has_flood_or_surge_flag IS FALSE" if exclude_surge_and_floodplain else ""

    shelters_sql = f"""
    SELECT
      shelter_id,
      shelter_name,
      address_1,
      city,
      state,
      zip,
      CONCAT(shelter_name, ', ', address_1, ', ', city, ', ', state, ' ', COALESCE(zip, '')) AS google_maps_lookup_query,
      ROUND(latitude, 5) AS latitude,
      ROUND(longitude, 5) AS longitude,
      CAST(evacuation_capacity AS INT64) AS evacuation_capacity,
      CAST(post_impact_capacity AS INT64) AS post_impact_capacity,
      wheelchair_status,
      generator_status,
      is_medical,
      in_surge_slosh_area,
      in_100_yr_floodplain,
      has_flood_or_surge_flag,
      usage,
      ROUND(hurricane_expected_annual_loss, 0) AS nearest_tract_hurricane_eal_usd,
      ROUND(coastal_flood_expected_annual_loss, 0) AS nearest_tract_coastal_flood_eal_usd,
      {dist_expr} AS straight_line_dist_km
    FROM `{PROJECT_ID}.{DATASET_ID}.shelter_hazard_exposure`
    WHERE LOWER(county_name) LIKE LOWER(@county_pattern)
      {dist_filter}
      {hazard_filter}
    ORDER BY {order_by}
    LIMIT {limit}
    """
    candidates = [
        dict(r)
        for r in bq.query(shelters_sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    ]

    return {
        "county_summary": summary,
        "critical_interpretation_rule": (
            "NEVER report `wheelchair_status = 'UNRECORDED'` as 'not accessible'. State the three counts "
            "separately (YES, NO, UNRECORDED) and use Grounding with Google Maps on individual candidate "
            "shelters (using their exact `google_maps_lookup_query` one building at a time) to verify "
            "whether each building is currently open, renamed, or wheelchair-accessible."
        ),
        "candidate_shelters": candidates,
    }


def assess_medical_and_power_dependency(
    county_name: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Analyze electricity-dependent Medicare beneficiaries (HHS emPOWER) and CMS nursing homes (`care_facilities`) relative to medical-needs and generator-equipped shelters.

    Args:
        county_name: Optional Florida county name (e.g. 'Miami-Dade', 'Pinellas', 'Hillsborough', 'Broward', 'Palm Beach'). Leave empty for top Florida counties by power-dependent DME count.
        limit: Maximum number of high-risk nursing homes or counties to return (default 10).

    Returns:
        Dictionary with HHS emPOWER electricity-dependent medical equipment counts, county generator/medical shelter ratios, and CMS nursing homes farthest from medical-needs or generator-backed shelters.
    """
    bq = _get_bq()
    limit = max(1, min(int(limit), 25))
    params = []
    county_filter_empower = ""
    county_filter_cf = ""

    if county_name and county_name.strip():
        clean_county = county_name.strip().replace(" County", "").replace(" county", "")
        county_filter_empower = "WHERE LOWER(p.county) LIKE LOWER(@county_pattern)"
        county_filter_cf = "WHERE LOWER(inferred_county_name) LIKE LOWER(@county_pattern)"
        params.append(bigquery.ScalarQueryParameter("county_pattern", "STRING", f"%{clean_county}%"))

    empower_sql = f"""
    WITH shelter_rollup AS (
      SELECT
        county_fips,
        COUNT(*) AS total_shelters,
        COUNTIF(is_medical IS TRUE) AS medical_shelters,
        CAST(SUM(IF(is_medical IS TRUE, evacuation_capacity, 0)) AS INT64) AS medical_shelter_capacity,
        COUNTIF(generator_onsite IS TRUE) AS generator_yes_shelters,
        COUNTIF(generator_onsite IS FALSE) AS generator_no_shelters,
        COUNTIF(generator_onsite IS NULL) AS generator_unrecorded_shelters,
        COUNTIF(generator_onsite IS TRUE AND COALESCE(in_surge_slosh_area, FALSE) IS FALSE AND COALESCE(in_100_yr_floodplain, FALSE) IS FALSE) AS surge_safe_generator_shelters
      FROM `{PROJECT_ID}.{DATASET_ID}.shelters`
      GROUP BY county_fips
    )
    SELECT
      p.county AS county_name,
      p.fips_code AS county_fips,
      CAST(p.medicare_benes AS INT64) AS medicare_beneficiaries,
      CAST(p.power_dependent_dme AS INT64) AS power_dependent_dme_users,
      CAST(p.o2_services_any_dme AS INT64) AS oxygen_dependent_dme_users,
      CAST(p.facility_esrd_dialysis_any_dme AS INT64) AS dialysis_dependent_dme_users,
      CAST(p.home_health_services_any_dme AS INT64) AS home_health_dme_users,
      CAST(p.athome_hospice_any_dme AS INT64) AS hospice_dme_users,
      p.power_dependent_is_censored,
      COALESCE(sr.total_shelters, 0) AS total_shelters,
      COALESCE(sr.medical_shelters, 0) AS designated_medical_shelters,
      COALESCE(sr.medical_shelter_capacity, 0) AS designated_medical_shelter_capacity,
      COALESCE(sr.generator_yes_shelters, 0) AS generator_yes_shelters,
      COALESCE(sr.generator_no_shelters, 0) AS generator_no_shelters,
      COALESCE(sr.generator_unrecorded_shelters, 0) AS generator_unrecorded_shelters,
      COALESCE(sr.surge_safe_generator_shelters, 0) AS surge_safe_generator_shelters,
      ROUND(
        SAFE_DIVIDE(p.power_dependent_dme, NULLIF(sr.generator_yes_shelters, 0)),
        1
      ) AS dme_users_per_confirmed_generator_shelter
    FROM `{PROJECT_ID}.{DATASET_ID}.power_dependent_counties` p
    LEFT JOIN shelter_rollup sr
      ON p.fips_code = sr.county_fips
    {county_filter_empower}
    ORDER BY p.power_dependent_dme DESC
    LIMIT {limit}
    """

    cf_sql = f"""
    SELECT
      cms_certification_number_ccn,
      provider_name,
      provider_address,
      citytown,
      zip_code,
      inferred_county_name AS county_name,
      number_of_certified_beds,
      ownership_type,
      ROUND(latitude, 5) AS latitude,
      ROUND(longitude, 5) AS longitude,
      nearest_any_shelter_km,
      nearest_any_shelter_name,
      nearest_medical_shelter_km,
      nearest_medical_shelter_name,
      nearest_wc_generator_safe_shelter_km,
      medical_shelters_within_10km
    FROM `{PROJECT_ID}.{DATASET_ID}.care_facility_evacuation_risk`
    {county_filter_cf}
    ORDER BY number_of_certified_beds DESC, nearest_medical_shelter_km DESC
    LIMIT {limit}
    """

    job_config = bigquery.QueryJobConfig(query_parameters=params)
    empower_rows = [dict(r) for r in bq.query(empower_sql, job_config=job_config).result()]
    cf_rows = [dict(r) for r in bq.query(cf_sql, job_config=job_config).result()]

    return {
        "scope": county_name or "Statewide Top Counties (Florida)",
        "statewide_context": (
            "Florida has 155 designated medical-needs shelters out of 2,793 total shelters (5.5%), "
            "207 shelters with confirmed onsite generators (2,318 UNRECORDED), and 694 CMS-certified "
            "nursing homes holding 84,537 beds."
        ),
        "power_dependent_counties": empower_rows,
        "nursing_home_facilities": cf_rows,
    }


def run_posthoc_equity_audit(county_name: str = "") -> dict[str, Any]:
    """Execute the post-hoc Equity & Reporting-Bias Audit comparing prioritized tracts and shelter accessibility blindspots against SVI Theme 3 (Racial & Ethnic Minority Status), poverty rate, income, and limited-English prevalence.

    Args:
        county_name: Optional Florida county name to audit (leave empty for the statewide Florida audit across all 5,160 tracts and 67 counties).

    Returns:
        Dictionary containing the post-hoc demographic comparison across priority deciles, reachability tiers (10 km threshold), and county-level accessibility reporting bias (`UNRECORDED` rate).
    """
    bq = _get_bq()
    params = []
    where_clause = "WHERE r.total_pop > 0 AND r.lat IS NOT NULL"

    if county_name and county_name.strip():
        clean_county = county_name.strip().replace(" County", "").replace(" county", "")
        where_clause += " AND LOWER(r.county_name) LIKE LOWER(@county_pattern)"
        params.append(bigquery.ScalarQueryParameter("county_pattern", "STRING", f"%{clean_county}%"))

    job_config = bigquery.QueryJobConfig(query_parameters=params)

    priority_sql = f"""
    WITH ranked AS (
      SELECT
        r.*,
        a.svi_minority_theme3_percentile,
        a.pct_minority_pop,
        NTILE(10) OVER (ORDER BY r.evacuation_priority_score DESC) AS priority_decile
      FROM `{PROJECT_ID}.{DATASET_ID}.tract_shelter_reachability` r
      LEFT JOIN `{PROJECT_ID}.{DATASET_ID}.equity_audit_svi_theme3` a
        USING (geo_id)
      {where_clause}
    )
    SELECT
      CASE
        WHEN priority_decile = 1 THEN 'Top 10% Prioritized Tracts (Decile 1)'
        WHEN priority_decile <= 3 THEN 'Next 20% Prioritized Tracts (Deciles 2-3)'
        ELSE 'Remaining 70% Tracts (Deciles 4-10)'
      END AS priority_tier,
      COUNT(*) AS tract_count,
      CAST(SUM(total_pop) AS INT64) AS total_population,
      CAST(SUM(households_no_vehicle) AS INT64) AS no_vehicle_households,
      ROUND(AVG(pct_no_vehicle), 1) AS avg_pct_no_vehicle,
      ROUND(AVG(pct_disability), 1) AS avg_pct_disability,
      ROUND(AVG(pct_mobile_homes), 1) AS avg_pct_mobile_homes,
      ROUND(AVG(nearest_any_shelter_km), 2) AS avg_nearest_shelter_km,
      ROUND(AVG(nearest_wc_yes_shelter_km), 2) AS avg_nearest_wc_yes_km,
      ROUND(AVG(svi_minority_theme3_percentile) * 100, 1) AS posthoc_avg_svi_theme3_percentile,
      ROUND(AVG(pct_minority_pop), 1) AS posthoc_avg_pct_minority_pop,
      ROUND(AVG(poverty_rate), 1) AS posthoc_avg_poverty_rate_pct,
      CAST(ROUND(AVG(median_income), 0) AS INT64) AS posthoc_avg_median_income_usd,
      ROUND(AVG(pct_limited_english), 1) AS posthoc_avg_pct_limited_english
    FROM ranked
    GROUP BY 1
    ORDER BY MIN(priority_decile)
    """
    priority_audit = [dict(r) for r in bq.query(priority_sql, job_config=job_config).result()]

    tier_sql = f"""
    SELECT
      r.reachability_tier,
      COUNT(*) AS tract_count,
      CAST(SUM(r.total_pop) AS INT64) AS total_population,
      CAST(SUM(r.households_no_vehicle) AS INT64) AS no_vehicle_households,
      ROUND(AVG(r.pct_disability), 1) AS avg_pct_disability,
      ROUND(AVG(a.pct_minority_pop), 1) AS posthoc_avg_pct_minority_pop,
      ROUND(AVG(r.poverty_rate), 1) AS posthoc_avg_poverty_rate_pct,
      CAST(ROUND(AVG(r.median_income), 0) AS INT64) AS posthoc_avg_median_income_usd
    FROM `{PROJECT_ID}.{DATASET_ID}.tract_shelter_reachability` r
    LEFT JOIN `{PROJECT_ID}.{DATASET_ID}.equity_audit_svi_theme3` a
      USING (geo_id)
    {where_clause}
    GROUP BY 1
    ORDER BY total_population DESC
    """
    tier_audit = [dict(r) for r in bq.query(tier_sql, job_config=job_config).result()]

    return {
        "scope": county_name or "Statewide (Florida)",
        "audit_methodology": (
            "Race and ethnicity (`RPL_THEME3`, `EP_MINRTY`, and composite `RPL_THEMES`) are strictly "
            "excluded from `vulnerability_tracts` and `evacuation_priority_score` inputs. Because structural "
            "barriers (vehicle access, housing type, disability, shelter distance) correlate with race and "
            "income, this post-hoc audit joins prioritized outputs to `equity_audit_svi_theme3` to verify "
            "whether high-need minority, low-income, and limited-English communities are equitably served "
            "or disproportionately trapped in `UNRECORDED` accessibility blindspots."
        ),
        "priority_decile_audit": priority_audit,
        "reachability_tier_audit": tier_audit,
    }


def record_shelter_accessibility_assessment(
    shelter_id: int,
    shelter_name: str,
    county_name: str,
    fema_wheelchair_status: str,
    assessed_wheelchair_status: str,
    operational_status: str,
    google_maps_place_id: str = "",
    google_maps_review_id: str = "",
    inspector_notes: str = "",
) -> dict[str, Any]:
    """Record a shelter accessibility/operational verification pointer in BigQuery (`evacuation_readiness.shelter_assessments`).

    Compliance Rule (Section 13 of Notebook):
    Never cache or export raw Google Maps text/descriptions. Store ONLY the exempt
    `google_maps_place_id` / `google_maps_review_id` pointers and the emergency
    manager's categorical assessment status.

    Args:
        shelter_id: FEMA shelter_id from `evacuation_readiness.shelters`.
        shelter_name: Registered shelter name.
        county_name: County name in Florida.
        fema_wheelchair_status: Original FEMA status ('YES', 'NO', or 'UNRECORDED').
        assessed_wheelchair_status: New categorical status ('VERIFIED_ACCESSIBLE', 'VERIFIED_NOT_ACCESSIBLE', 'UNCONFIRMED_NEEDS_SITE_VISIT').
        operational_status: Operational status ('OPEN_OPERATIONAL', 'RENAMED_SAME_BUILDING', 'CLOSED_OR_MOVED', 'UNVERIFIED').
        google_maps_place_id: Optional Google Maps `place_id` pointer (explicitly permitted to persist by Google Maps terms).
        google_maps_review_id: Optional Google Maps `review_id` pointer (explicitly permitted to persist by Google Maps terms).
        inspector_notes: Actionable planner note (do not paste raw Google Maps review text).

    Returns:
        Confirmation dictionary with the persisted record metadata.
    """
    bq = _get_bq()
    assessment_id = str(uuid.uuid4())[:12]
    now_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

    query = f"""
    INSERT INTO `{PROJECT_ID}.{DATASET_ID}.shelter_assessments`
    (assessment_id, shelter_id, shelter_name, county_name, fema_wheelchair_status,
     assessed_wheelchair_status, operational_status, google_maps_place_id,
     google_maps_review_id, assessment_source, inspector_notes, assessed_at)
    VALUES
    (@assessment_id, @shelter_id, @shelter_name, @county_name, @fema_wheelchair_status,
     @assessed_wheelchair_status, @operational_status, @google_maps_place_id,
     @google_maps_review_id, 'ADK_AGENT_MAPS_POINTER_CHECK', @inspector_notes, TIMESTAMP(@assessed_at))
    """
    params = [
        bigquery.ScalarQueryParameter("assessment_id", "STRING", assessment_id),
        bigquery.ScalarQueryParameter("shelter_id", "INT64", int(shelter_id)),
        bigquery.ScalarQueryParameter("shelter_name", "STRING", shelter_name),
        bigquery.ScalarQueryParameter("county_name", "STRING", county_name),
        bigquery.ScalarQueryParameter("fema_wheelchair_status", "STRING", fema_wheelchair_status),
        bigquery.ScalarQueryParameter("assessed_wheelchair_status", "STRING", assessed_wheelchair_status),
        bigquery.ScalarQueryParameter("operational_status", "STRING", operational_status),
        bigquery.ScalarQueryParameter("google_maps_place_id", "STRING", google_maps_place_id or ""),
        bigquery.ScalarQueryParameter("google_maps_review_id", "STRING", google_maps_review_id or ""),
        bigquery.ScalarQueryParameter("inspector_notes", "STRING", inspector_notes or ""),
        bigquery.ScalarQueryParameter("assessed_at", "STRING", now_ts),
    ]
    bq.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()

    return {
        "status": "RECORDED_IN_BIGQUERY",
        "table": f"{PROJECT_ID}.{DATASET_ID}.shelter_assessments",
        "assessment_id": assessment_id,
        "shelter_id": shelter_id,
        "shelter_name": shelter_name,
        "county_name": county_name,
        "fema_wheelchair_status": fema_wheelchair_status,
        "assessed_wheelchair_status": assessed_wheelchair_status,
        "operational_status": operational_status,
        "google_maps_place_id": google_maps_place_id,
        "compliance_note": (
            "Persisted only `google_maps_place_id` / `google_maps_review_id` pointer and categorical status "
            "in compliance with Google Maps Grounding Terms of Service."
        ),
    }


def get_recorded_shelter_assessments(county_name: str = "") -> dict[str, Any]:
    """Retrieve previously recorded shelter accessibility assessments and Google Maps `place_id` pointers from `evacuation_readiness.shelter_assessments`.

    Args:
        county_name: Optional county name filter.

    Returns:
        Dictionary of recorded shelter assessments.
    """
    bq = _get_bq()
    params = []
    where_sql = ""
    if county_name and county_name.strip():
        clean_county = county_name.strip().replace(" County", "").replace(" county", "")
        where_sql = "WHERE LOWER(county_name) LIKE LOWER(@county_pattern)"
        params.append(bigquery.ScalarQueryParameter("county_pattern", "STRING", f"%{clean_county}%"))

    query = f"""
    SELECT
      assessment_id,
      shelter_id,
      shelter_name,
      county_name,
      fema_wheelchair_status,
      assessed_wheelchair_status,
      operational_status,
      google_maps_place_id,
      google_maps_review_id,
      assessment_source,
      inspector_notes,
      CAST(assessed_at AS STRING) AS assessed_at
    FROM `{PROJECT_ID}.{DATASET_ID}.shelter_assessments`
    {where_sql}
    ORDER BY assessed_at DESC
    LIMIT 50
    """
    rows = [dict(r) for r in bq.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()]
    return {
        "count": len(rows),
        "assessments": rows,
    }
