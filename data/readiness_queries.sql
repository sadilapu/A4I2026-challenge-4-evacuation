-- ============================================================================
-- Challenge 4: Evacuation Readiness & Vulnerable Community Planning (FL)
-- Project: qwiklabs-gcp-03-bb316766e33b | Dataset: evacuation_readiness
-- ============================================================================
-- Key Domain Guardrails Enforced in SQL:
-- 1. Never collapse NULL wheelchair_accessible or generator_onsite into FALSE.
--    Always report 'YES', 'NO', and 'UNRECORDED' as three distinct states.
-- 2. All BigQuery ST_DISTANCE calculations are straight-line geodesic meters
--    (converted to km). Driving routes/times are fetched at runtime via
--    Grounding with Google Maps (with routing enabled).
-- 3. SVI Theme 3 (Racial & Ethnic Minority Status) is excluded from prioritization
--    inputs and used strictly in the post-hoc Equity Audit (data/equity_audit.py).
-- 4. CDC PLACES pct_lacktrpt is NULL in Florida; vehicle access is measured via
--    ACS households_no_vehicle and CDC SVI pct_no_vehicle (vehicle ownership).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. View: shelter_hazard_exposure
-- Enriches every shelter with explicit 3-state accessibility/generator labels,
-- county emPOWER power-dependency context, and nearest tract hazard exposure.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.shelter_hazard_exposure` AS
WITH shelter_nearest_hazard AS (
  SELECT
    s.shelter_id,
    ARRAY_AGG(
      STRUCT(
        h.geo_id AS nearest_hazard_tract_id,
        h.HRCN_AFREQ AS hurricane_annual_freq,
        h.HRCN_EALT AS hurricane_expected_annual_loss,
        h.CFLD_AFREQ AS coastal_flood_annual_freq,
        h.CFLD_EALT AS coastal_flood_expected_annual_loss,
        ROUND(
          ST_DISTANCE(
            ST_GEOGPOINT(s.longitude, s.latitude),
            ST_GEOGPOINT(v.lon, v.lat)
          ) / 1000.0,
          2
        ) AS tract_centroid_dist_km
      )
      ORDER BY ST_DISTANCE(ST_GEOGPOINT(s.longitude, s.latitude), ST_GEOGPOINT(v.lon, v.lat))
      LIMIT 1
    )[OFFSET(0)] AS haz
  FROM `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.shelters` s
  CROSS JOIN `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.vulnerability_tracts` v
  JOIN `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.hazard_tracts` h
    ON v.geo_id = h.geo_id
  WHERE s.latitude IS NOT NULL AND v.lat IS NOT NULL
  GROUP BY s.shelter_id
)
SELECT
  s.shelter_id,
  s.shelter_name,
  s.address_1,
  s.city,
  s.county_name,
  s.county_fips,
  s.state,
  s.zip,
  s.latitude,
  s.longitude,
  COALESCE(s.evacuation_capacity, 0) AS evacuation_capacity,
  COALESCE(s.post_impact_capacity, 0) AS post_impact_capacity,
  s.wheelchair_accessible,
  CASE
    WHEN s.wheelchair_accessible IS TRUE THEN 'YES'
    WHEN s.wheelchair_accessible IS FALSE THEN 'NO'
    ELSE 'UNRECORDED'
  END AS wheelchair_status,
  s.generator_onsite,
  CASE
    WHEN s.generator_onsite IS TRUE THEN 'YES'
    WHEN s.generator_onsite IS FALSE THEN 'NO'
    ELSE 'UNRECORDED'
  END AS generator_status,
  s.self_sufficient_electricity,
  COALESCE(s.in_surge_slosh_area, FALSE) AS in_surge_slosh_area,
  COALESCE(s.in_100_yr_floodplain, FALSE) AS in_100_yr_floodplain,
  COALESCE(s.is_medical, FALSE) AS is_medical,
  COALESCE(s.is_functional, FALSE) AS is_functional,
  s.pet_accommodations_code,
  s.population_code,
  s.usage,
  s.shelter_status_code,
  nh.haz.nearest_hazard_tract_id,
  nh.haz.hurricane_annual_freq,
  nh.haz.hurricane_expected_annual_loss,
  nh.haz.coastal_flood_annual_freq,
  nh.haz.coastal_flood_expected_annual_loss,
  p.medicare_benes AS county_medicare_benes,
  p.power_dependent_dme AS county_power_dependent_dme,
  p.o2_services_any_dme AS county_o2_dme,
  p.facility_esrd_dialysis_any_dme AS county_dialysis_dme,
  -- Flag shelters exposed to storm surge or 100-yr floodplains
  (COALESCE(s.in_surge_slosh_area, FALSE) OR COALESCE(s.in_100_yr_floodplain, FALSE)) AS has_flood_or_surge_flag
FROM `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.shelters` s
LEFT JOIN shelter_nearest_hazard nh
  USING (shelter_id)
LEFT JOIN `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.power_dependent_counties` p
  ON s.county_fips = p.fips_code;


-- ----------------------------------------------------------------------------
-- 2. View: tract_shelter_reachability
-- Computes straight-line distance from every Florida census tract centroid to:
--   - nearest shelter of any kind
--   - nearest confirmed wheelchair-accessible shelter (wheelchair_accessible IS TRUE)
--   - nearest medical-needs shelter (is_medical IS TRUE)
--   - nearest flood/surge-safe shelter with generator
-- And counts shelters within 5 km and 10 km broken out by YES / NO / UNRECORDED.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.tract_shelter_reachability` AS
WITH pair_distances AS (
  SELECT
    v.geo_id,
    s.shelter_id,
    s.shelter_name,
    s.address_1,
    s.city,
    COALESCE(s.evacuation_capacity, s.post_impact_capacity, 0) AS effective_capacity,
    s.wheelchair_accessible,
    CASE
      WHEN s.wheelchair_accessible IS TRUE THEN 'YES'
      WHEN s.wheelchair_accessible IS FALSE THEN 'NO'
      ELSE 'UNRECORDED'
    END AS wc_status,
    s.generator_onsite,
    COALESCE(s.is_medical, FALSE) AS is_medical,
    COALESCE(s.in_surge_slosh_area, FALSE) AS in_surge_slosh_area,
    COALESCE(s.in_100_yr_floodplain, FALSE) AS in_100_yr_floodplain,
    ST_DISTANCE(
      ST_GEOGPOINT(v.lon, v.lat),
      ST_GEOGPOINT(s.longitude, s.latitude)
    ) / 1000.0 AS dist_km
  FROM `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.vulnerability_tracts` v
  CROSS JOIN `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.shelters` s
  WHERE v.lat IS NOT NULL AND s.latitude IS NOT NULL
),
tract_Rollup AS (
  SELECT
    geo_id,
    -- Nearest shelter of any kind
    ROUND(MIN(dist_km), 2) AS nearest_any_shelter_km,
    ARRAY_AGG(
      STRUCT(shelter_id, shelter_name, address_1, city, effective_capacity, wc_status, ROUND(dist_km, 2) AS dist_km)
      ORDER BY dist_km ASC LIMIT 1
    )[OFFSET(0)] AS nearest_any,
    -- Nearest confirmed wheelchair-accessible shelter (wheelchair_accessible IS TRUE)
    ROUND(MIN(IF(wheelchair_accessible IS TRUE, dist_km, NULL)), 2) AS nearest_wc_yes_shelter_km,
    ARRAY_AGG(
      IF(
        wheelchair_accessible IS TRUE,
        STRUCT(shelter_id, shelter_name, address_1, city, effective_capacity, ROUND(dist_km, 2) AS dist_km),
        NULL
      ) IGNORE NULLS
      ORDER BY dist_km ASC LIMIT 1
    )[SAFE_OFFSET(0)] AS nearest_wc_yes,
    -- Nearest medical-needs shelter
    ROUND(MIN(IF(is_medical IS TRUE, dist_km, NULL)), 2) AS nearest_medical_shelter_km,
    ARRAY_AGG(
      IF(
        is_medical IS TRUE,
        STRUCT(shelter_id, shelter_name, address_1, city, effective_capacity, ROUND(dist_km, 2) AS dist_km),
        NULL
      ) IGNORE NULLS
      ORDER BY dist_km ASC LIMIT 1
    )[SAFE_OFFSET(0)] AS nearest_medical,
    -- Nearest flood/surge-free shelter with generator onsite
    ROUND(
      MIN(
        IF(
          in_surge_slosh_area IS FALSE AND in_100_yr_floodplain IS FALSE AND generator_onsite IS TRUE,
          dist_km,
          NULL
        )
      ),
      2
    ) AS nearest_resilient_shelter_km,
    -- Counts within 5 km (walk / short shuttle radius)
    COUNTIF(dist_km <= 5.0) AS shelters_within_5km_total,
    COUNTIF(dist_km <= 5.0 AND wheelchair_accessible IS TRUE) AS shelters_within_5km_wc_yes,
    COUNTIF(dist_km <= 5.0 AND wheelchair_accessible IS FALSE) AS shelters_within_5km_wc_no,
    COUNTIF(dist_km <= 5.0 AND wheelchair_accessible IS NULL) AS shelters_within_5km_wc_unrecorded,
    -- Counts within 10 km (no-vehicle emergency reachability threshold)
    COUNTIF(dist_km <= 10.0) AS shelters_within_10km_total,
    COUNTIF(dist_km <= 10.0 AND wheelchair_accessible IS TRUE) AS shelters_within_10km_wc_yes,
    COUNTIF(dist_km <= 10.0 AND wheelchair_accessible IS FALSE) AS shelters_within_10km_wc_no,
    COUNTIF(dist_km <= 10.0 AND wheelchair_accessible IS NULL) AS shelters_within_10km_wc_unrecorded,
    SUM(IF(dist_km <= 10.0, effective_capacity, 0)) AS capacity_within_10km
  FROM pair_distances
  GROUP BY geo_id
)
SELECT
  v.geo_id,
  v.county_fips,
  p.county AS county_name,
  v.lat,
  v.lon,
  v.total_pop,
  v.households,
  v.households_no_vehicle,
  v.pop_65_plus,
  v.mobile_homes,
  v.group_quarters_pop,
  v.limited_english_spanish,
  IF(v.median_income > 0, v.median_income, NULL) AS median_income,
  ROUND(IF(v.poverty_rate BETWEEN 0 AND 1, v.poverty_rate * 100.0, v.poverty_rate), 1) AS poverty_rate,
  v.pct_disability,
  v.pct_age_65_plus,
  v.pct_no_vehicle,
  v.pct_limited_english,
  v.pct_mobile_homes,
  v.pct_group_quarters,
  v.pct_no_internet,
  v.svi_socioeconomic,
  v.svi_household,
  v.svi_housing_transport,
  v.pct_indeplive,
  v.pct_mobility,
  v.pct_selfcare,
  h.HRCN_AFREQ AS hurricane_annual_freq,
  h.HRCN_EALT AS hurricane_expected_annual_loss,
  h.CFLD_AFREQ AS coastal_flood_annual_freq,
  h.CFLD_EALT AS coastal_flood_expected_annual_loss,
  r.nearest_any_shelter_km,
  r.nearest_any.shelter_id AS nearest_any_shelter_id,
  r.nearest_any.shelter_name AS nearest_any_shelter_name,
  r.nearest_any.address_1 AS nearest_any_shelter_address,
  r.nearest_any.city AS nearest_any_shelter_city,
  r.nearest_any.wc_status AS nearest_any_shelter_wc_status,
  r.nearest_wc_yes_shelter_km,
  r.nearest_wc_yes.shelter_id AS nearest_wc_yes_shelter_id,
  r.nearest_wc_yes.shelter_name AS nearest_wc_yes_shelter_name,
  r.nearest_wc_yes.address_1 AS nearest_wc_yes_shelter_address,
  r.nearest_wc_yes.city AS nearest_wc_yes_shelter_city,
  r.nearest_medical_shelter_km,
  r.nearest_medical.shelter_name AS nearest_medical_shelter_name,
  r.nearest_resilient_shelter_km,
  r.shelters_within_5km_total,
  r.shelters_within_5km_wc_yes,
  r.shelters_within_5km_wc_no,
  r.shelters_within_5km_wc_unrecorded,
  r.shelters_within_10km_total,
  r.shelters_within_10km_wc_yes,
  r.shelters_within_10km_wc_no,
  r.shelters_within_10km_wc_unrecorded,
  r.capacity_within_10km,
  -- Explicit Reachability Tier Classification (distinguishing paperwork gaps from physical gaps)
  CASE
    WHEN r.nearest_any_shelter_km IS NULL THEN 'NO_COORDINATES'
    WHEN r.nearest_any_shelter_km > 10.0 THEN 'ISOLATED_NO_SHELTER_WITHIN_10KM'
    WHEN r.nearest_wc_yes_shelter_km <= 10.0 THEN 'REACHABLE_CONFIRMED_WC_WITHIN_10KM'
    WHEN r.shelters_within_10km_wc_unrecorded > 0 THEN 'UNRECORDED_ACCESSIBILITY_BLINDSPOT_10KM'
    ELSE 'CONFIRMED_INACCESSIBLE_WITHIN_10KM'
  END AS reachability_tier,
  -- Composite Evacuation Readiness Priority Score (0-100 scale approximation)
  -- Strictly excludes race/ethnicity (SVI Theme 3) per Challenge 4 guardrails.
  ROUND(
    (COALESCE(v.pct_no_vehicle, 0) * 2.2) +
    (LEAST(COALESCE(v.households_no_vehicle, 0) / 15.0, 25.0)) +
    (COALESCE(v.pct_disability, 0) * 1.4) +
    (COALESCE(v.pct_mobility, 0) * 1.2) +
    (COALESCE(v.pct_age_65_plus, 0) * 0.5) +
    (COALESCE(v.pct_mobile_homes, 0) * 0.6) +
    (LEAST(COALESCE(r.nearest_any_shelter_km, 25.0), 25.0) * 1.5) +
    (LEAST(COALESCE(r.nearest_wc_yes_shelter_km, 35.0), 35.0) * 0.8) +
    (LOG10(GREATEST(COALESCE(h.HRCN_EALT, 0) + COALESCE(h.CFLD_EALT, 0), 1.0)) * 3.0),
    2
  ) AS evacuation_priority_score
FROM `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.vulnerability_tracts` v
LEFT JOIN tract_Rollup r
  USING (geo_id)
LEFT JOIN `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.hazard_tracts` h
  USING (geo_id)
LEFT JOIN `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.power_dependent_counties` p
  ON v.county_fips = p.fips_code;


-- ----------------------------------------------------------------------------
-- 3. View: care_facility_evacuation_risk
-- Maps every CMS-certified nursing home (694 in FL) to its nearest general
-- shelter, nearest medical-needs shelter, and nearest confirmed accessible
-- shelter with backup power.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.care_facility_evacuation_risk` AS
WITH cf_shelter_pairs AS (
  SELECT
    c.cms_certification_number_ccn,
    c.provider_name,
    c.provider_address,
    c.citytown,
    c.zip_code,
    c.number_of_certified_beds,
    c.ownership_type,
    c.latitude,
    c.longitude,
    s.shelter_id,
    s.shelter_name,
    s.county_name,
    s.county_fips,
    s.wheelchair_accessible,
    s.generator_onsite,
    COALESCE(s.is_medical, FALSE) AS is_medical,
    COALESCE(s.in_surge_slosh_area, FALSE) AS in_surge_slosh_area,
    COALESCE(s.in_100_yr_floodplain, FALSE) AS in_100_yr_floodplain,
    ST_DISTANCE(
      ST_GEOGPOINT(c.longitude, c.latitude),
      ST_GEOGPOINT(s.longitude, s.latitude)
    ) / 1000.0 AS dist_km
  FROM `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.care_facilities` c
  CROSS JOIN `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.shelters` s
  WHERE c.latitude IS NOT NULL AND s.latitude IS NOT NULL
)
SELECT
  cms_certification_number_ccn,
  ANY_VALUE(provider_name) AS provider_name,
  ANY_VALUE(provider_address) AS provider_address,
  ANY_VALUE(citytown) AS citytown,
  ANY_VALUE(zip_code) AS zip_code,
  ANY_VALUE(number_of_certified_beds) AS number_of_certified_beds,
  ANY_VALUE(ownership_type) AS ownership_type,
  ANY_VALUE(latitude) AS latitude,
  ANY_VALUE(longitude) AS longitude,
  ARRAY_AGG(county_name ORDER BY dist_km ASC LIMIT 1)[OFFSET(0)] AS inferred_county_name,
  ARRAY_AGG(county_fips ORDER BY dist_km ASC LIMIT 1)[OFFSET(0)] AS inferred_county_fips,
  ROUND(MIN(dist_km), 2) AS nearest_any_shelter_km,
  ARRAY_AGG(shelter_name ORDER BY dist_km ASC LIMIT 1)[OFFSET(0)] AS nearest_any_shelter_name,
  ROUND(MIN(IF(is_medical IS TRUE, dist_km, NULL)), 2) AS nearest_medical_shelter_km,
  ARRAY_AGG(IF(is_medical IS TRUE, shelter_name, NULL) IGNORE NULLS ORDER BY dist_km ASC LIMIT 1)[SAFE_OFFSET(0)] AS nearest_medical_shelter_name,
  ROUND(
    MIN(
      IF(
        wheelchair_accessible IS TRUE AND generator_onsite IS TRUE AND in_surge_slosh_area IS FALSE,
        dist_km,
        NULL
      )
    ),
    2
  ) AS nearest_wc_generator_safe_shelter_km,
  COUNTIF(dist_km <= 10.0 AND is_medical IS TRUE) AS medical_shelters_within_10km
FROM cf_shelter_pairs
GROUP BY cms_certification_number_ccn;


-- ----------------------------------------------------------------------------
-- 4. Operational Table: shelter_assessments
-- Stores verified accessibility/operational assessments and Google Maps
-- place_id / review_id pointers (compliant with Google Maps Grounding Terms:
-- never caches raw Google Maps content, only place_id/review_id pointers and
-- emergency manager assessment status).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.shelter_assessments` (
  assessment_id STRING,
  shelter_id INT64,
  shelter_name STRING,
  county_name STRING,
  fema_wheelchair_status STRING,
  assessed_wheelchair_status STRING,
  operational_status STRING,
  google_maps_place_id STRING,
  google_maps_review_id STRING,
  assessment_source STRING,
  inspector_notes STRING,
  assessed_at TIMESTAMP
);
