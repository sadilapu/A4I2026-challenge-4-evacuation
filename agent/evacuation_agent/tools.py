"""Custom Python FunctionTools for the Challenge 4 Evacuation Readiness ADK Agent.

Implements:
1. audit_county_shelters()          - Option 1: Ghost Shelter & Accessibility Auditor
2. find_zero_car_transit_gaps()     - Option 2: Zero-Car Transit Lifeline
3. check_medical_power_gaps()       - Option 3: Generator-Blind Nursing Home Alert
4. verify_place_with_maps_grounding()- Live Grounding with Google Maps + Routing (1 place at a time)
5. run_equity_audit()               - Post-Hoc Demographic & Paperwork Bias Audit
6. record_field_assessment()        - Shelter Operator Field Assessment Write-Back Loop
"""

from __future__ import annotations

import base64
import datetime
import html
import io
import math
import re
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from google import genai
from google.cloud import bigquery
from google.genai import types

from .config import (
    BQ_LOCATION,
    DATASET,
    DEFAULT_COUNTY_FIPS,
    FALLBACK_MODEL_NAME,
    LOCATION,
    MODEL_NAME,
    PROJECT_ID,
)

_bq_client: Optional[bigquery.Client] = None
_genai_client: Optional[genai.Client] = None
_tts_client: Optional[genai.Client] = None
_counties_cache: Optional[List[Dict[str, Any]]] = None
_city_to_county_cache: Optional[Dict[str, Dict[str, Any]]] = None


def get_bq_client() -> bigquery.Client:
    """Return a cached BigQuery client for PROJECT_ID."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=PROJECT_ID, location=BQ_LOCATION)
    return _bq_client


def get_genai_client() -> genai.Client:
    """Return a cached Vertex AI GenAI client configured for global endpoint."""
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location=LOCATION,
        )
    return _genai_client


def get_tts_client() -> genai.Client:
    """Return a cached Vertex AI GenAI client configured for us-central1 TTS."""
    global _tts_client
    if _tts_client is None:
        _tts_client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location="us-central1",
        )
    return _tts_client


_FALLBACK_COUNTIES: List[Dict[str, Any]] = [
    {"county_fips": "12071", "county_name": "Lee", "state": "FL", "total_shelters": 100, "center_lat": 26.5965, "center_lon": -81.8414, "total_capacity": 67573},
    {"county_fips": "12086", "county_name": "Miami-Dade", "state": "FL", "total_shelters": 85, "center_lat": 25.7617, "center_lon": -80.1918, "total_capacity": 120000},
    {"county_fips": "12011", "county_name": "Broward", "state": "FL", "total_shelters": 42, "center_lat": 26.1224, "center_lon": -80.1373, "total_capacity": 58000},
    {"county_fips": "12057", "county_name": "Hillsborough", "state": "FL", "total_shelters": 68, "center_lat": 27.9506, "center_lon": -82.4572, "total_capacity": 74000},
    {"county_fips": "12103", "county_name": "Pinellas", "state": "FL", "total_shelters": 45, "center_lat": 27.8764, "center_lon": -82.7779, "total_capacity": 49000},
    {"county_fips": "12095", "county_name": "Orange", "state": "FL", "total_shelters": 56, "center_lat": 28.5383, "center_lon": -81.3792, "total_capacity": 62000},
    {"county_fips": "12099", "county_name": "Palm Beach", "state": "FL", "total_shelters": 48, "center_lat": 26.7056, "center_lon": -80.0364, "total_capacity": 64000},
    {"county_fips": "12031", "county_name": "Duval", "state": "FL", "total_shelters": 40, "center_lat": 30.3322, "center_lon": -81.6557, "total_capacity": 51000},
    {"county_fips": "12021", "county_name": "Collier", "state": "FL", "total_shelters": 31, "center_lat": 26.1420, "center_lon": -81.7948, "total_capacity": 28000},
    {"county_fips": "12115", "county_name": "Sarasota", "state": "FL", "total_shelters": 29, "center_lat": 27.3364, "center_lon": -82.5307, "total_capacity": 26000},
    {"county_fips": "12015", "county_name": "Charlotte", "state": "FL", "total_shelters": 18, "center_lat": 26.9342, "center_lon": -82.0465, "total_capacity": 16000},
    {"county_fips": "12105", "county_name": "Polk", "state": "FL", "total_shelters": 52, "center_lat": 28.0395, "center_lon": -81.9498, "total_capacity": 45000},
    {"county_fips": "12009", "county_name": "Brevard", "state": "FL", "total_shelters": 38, "center_lat": 28.2639, "center_lon": -80.7214, "total_capacity": 39000},
    {"county_fips": "12127", "county_name": "Volusia", "state": "FL", "total_shelters": 44, "center_lat": 29.0280, "center_lon": -81.0755, "total_capacity": 41000},
    {"county_fips": "12101", "county_name": "Pasco", "state": "FL", "total_shelters": 36, "center_lat": 28.3232, "center_lon": -82.4319, "total_capacity": 35000},
    {"county_fips": "12081", "county_name": "Manatee", "state": "FL", "total_shelters": 27, "center_lat": 27.4989, "center_lon": -82.5748, "total_capacity": 29000},
    {"county_fips": "12073", "county_name": "Leon", "state": "FL", "total_shelters": 24, "center_lat": 30.4383, "center_lon": -84.2807, "total_capacity": 22000},
    {"county_fips": "12033", "county_name": "Escambia", "state": "FL", "total_shelters": 22, "center_lat": 30.4213, "center_lon": -87.2169, "total_capacity": 21000},
    {"county_fips": "12087", "county_name": "Monroe", "state": "FL", "total_shelters": 12, "center_lat": 24.5551, "center_lon": -81.7800, "total_capacity": 8500},
    {"county_fips": "12001", "county_name": "Alachua", "state": "FL", "total_shelters": 25, "center_lat": 29.6516, "center_lon": -82.3248, "total_capacity": 20000},
]

_KNOWN_CITY_TO_FIPS: Dict[str, str] = {
    "fort myers": "12071",
    "north fort myers": "12071",
    "fort myers beach": "12071",
    "cape coral": "12071",
    "lehigh acres": "12071",
    "estero": "12071",
    "bonita springs": "12071",
    "sanibel": "12071",
    "miami": "12086",
    "miami beach": "12086",
    "hialeah": "12086",
    "homestead": "12086",
    "coral gables": "12086",
    "doral": "12086",
    "kendall": "12086",
    "north miami": "12086",
    "fort lauderdale": "12011",
    "hollywood": "12011",
    "pembroke pines": "12011",
    "coral springs": "12011",
    "pompano beach": "12011",
    "miramar": "12011",
    "sunrise": "12011",
    "plantation": "12011",
    "davie": "12011",
    "tampa": "12057",
    "brandon": "12057",
    "plant city": "12057",
    "riverview": "12057",
    "temple terrace": "12057",
    "st. petersburg": "12103",
    "st petersburg": "12103",
    "saint petersburg": "12103",
    "clearwater": "12103",
    "largo": "12103",
    "pinellas park": "12103",
    "dunedin": "12103",
    "tarpon springs": "12103",
    "orlando": "12095",
    "winter park": "12095",
    "apopka": "12095",
    "ocoee": "12095",
    "winter garden": "12095",
    "west palm beach": "12099",
    "boca raton": "12099",
    "boynton beach": "12099",
    "delray beach": "12099",
    "jupiter": "12099",
    "wellington": "12099",
    "lake worth": "12099",
    "palm beach gardens": "12099",
    "jacksonville": "12031",
    "jacksonville beach": "12031",
    "naples": "12021",
    "marco island": "12021",
    "immokalee": "12021",
    "sarasota": "12115",
    "venice": "12115",
    "north port": "12115",
    "port charlotte": "12015",
    "punta gorda": "12015",
    "bradenton": "12081",
    "palmetto": "12081",
    "lakeland": "12105",
    "winter haven": "12105",
    "bartow": "12105",
    "haines city": "12105",
    "melbourne": "12009",
    "palm bay": "12009",
    "titusville": "12009",
    "cocoa": "12009",
    "rockledge": "12009",
    "daytona beach": "12127",
    "deltona": "12127",
    "ormond beach": "12127",
    "new smyrna beach": "12127",
    "deland": "12127",
    "new port richey": "12101",
    "zephyrhills": "12101",
    "dade city": "12101",
    "wesley chapel": "12101",
    "tallahassee": "12073",
    "pensacola": "12033",
    "key west": "12087",
    "marathon": "12087",
    "key largo": "12087",
    "islamorada": "12087",
    "gainesville": "12001",
    "panama city": "12005",
    "kissimmee": "12097",
    "st. cloud": "12097",
    "sanford": "12117",
    "altamonte springs": "12117",
    "oviedo": "12117",
    "ocala": "12083",
    "st. augustine": "12109",
    "st augustine": "12109",
    "port st. lucie": "12111",
    "port st lucie": "12111",
    "fort pierce": "12111",
    "vero beach": "12061",
    "stuart": "12085",
    "palm coast": "12035",
    "spring hill": "12053",
    "brooksville": "12053",
    "fort walton beach": "12091",
    "destin": "12091",
    "crestview": "12091",
    "milton": "12113",
}


def list_available_counties() -> List[Dict[str, Any]]:
    """Return all counties available in BigQuery `shelters` with center coordinates and capacities.

    Caches the result in module-level `_counties_cache` and `_city_to_county_cache` so
    subsequent calls complete in <1ms.
    """
    global _counties_cache, _city_to_county_cache
    if _counties_cache is not None:
        return _counties_cache

    bq = get_bq_client()
    t_shelters = f"`{PROJECT_ID}.{DATASET}.shelters`"

    counties_sql = f"""
    SELECT
      county_fips,
      county_name,
      state,
      COUNT(*) AS total_shelters,
      AVG(latitude) AS center_lat,
      AVG(longitude) AS center_lon,
      SUM(
        CASE
          WHEN GREATEST(COALESCE(evacuation_capacity, 0), COALESCE(post_impact_capacity, 0)) BETWEEN 0 AND 100000
          THEN GREATEST(COALESCE(evacuation_capacity, 0), COALESCE(post_impact_capacity, 0))
          ELSE 0
        END
      ) AS total_capacity
    FROM {t_shelters}
    WHERE county_fips IS NOT NULL
      AND state = 'FL'
      AND latitude IS NOT NULL
      AND longitude IS NOT NULL
    GROUP BY county_fips, county_name, state
    ORDER BY
      CASE WHEN county_fips = '12071' THEN 0 ELSE 1 END,
      county_name ASC
    """

    city_sql = f"""
    SELECT
      LOWER(TRIM(city)) AS city_lower,
      ANY_VALUE(county_fips) AS county_fips,
      ANY_VALUE(county_name) AS county_name,
      ANY_VALUE(state) AS state
    FROM {t_shelters}
    WHERE city IS NOT NULL
      AND county_fips IS NOT NULL
      AND state = 'FL'
    GROUP BY LOWER(TRIM(city))
    """

    try:
        rows = list(bq.query(counties_sql).result())
        by_fips: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            fips = str(r.county_fips).strip()
            if not fips:
                continue
            cname = str(r.county_name or "").strip()
            if cname.isupper():
                cname = cname.title()
            st = str(r.state or "FL").strip().upper()
            cnt = int(r.total_shelters or 0)
            cap = int(r.total_capacity or 0)
            clat = round(float(r.center_lat), 5) if r.center_lat is not None else 26.5965
            clon = round(float(r.center_lon), 5) if r.center_lon is not None else -81.8414

            if fips not in by_fips:
                by_fips[fips] = {
                    "county_fips": fips,
                    "county_name": cname or fips,
                    "state": st,
                    "total_shelters": cnt,
                    "center_lat": clat,
                    "center_lon": clon,
                    "total_capacity": cap,
                }
            else:
                prev = by_fips[fips]
                total_sh = prev["total_shelters"] + cnt
                prev["center_lat"] = round(
                    (prev["center_lat"] * prev["total_shelters"] + clat * cnt) / max(total_sh, 1),
                    5,
                )
                prev["center_lon"] = round(
                    (prev["center_lon"] * prev["total_shelters"] + clon * cnt) / max(total_sh, 1),
                    5,
                )
                prev["total_shelters"] = total_sh
                prev["total_capacity"] += cap

        counties_list = sorted(
            by_fips.values(),
            key=lambda x: (
                0 if x["state"] == "FL" else 1,
                0 if x["county_fips"] == DEFAULT_COUNTY_FIPS else 1,
                x["county_name"].lower(),
            ),
        )
        _counties_cache = counties_list if counties_list else list(_FALLBACK_COUNTIES)

        city_map: Dict[str, Dict[str, Any]] = {}
        for known_city, known_fips in _KNOWN_CITY_TO_FIPS.items():
            if known_fips in by_fips:
                city_map[known_city] = by_fips[known_fips]

        _city_to_county_cache = city_map
    except Exception:
        _counties_cache = list(_FALLBACK_COUNTIES)
        by_fips_fb = {c["county_fips"]: c for c in _counties_cache}
        _city_to_county_cache = {
            city: by_fips_fb[fips]
            for city, fips in _KNOWN_CITY_TO_FIPS.items()
            if fips in by_fips_fb
        }

    return _counties_cache


def resolve_county_from_query(
    question: str,
    fallback_fips: str = DEFAULT_COUNTY_FIPS,
) -> Dict[str, Any]:
    """Dynamically detect if `question` mentions any county name, city name, or 5-digit FIPS code.

    Args:
        question: User's natural-language voice or text prompt.
        fallback_fips: Fallback county FIPS code if no county/city is mentioned in `question`.

    Returns:
        Dictionary with county metadata and `matched_from_query` boolean flag.
    """
    counties = list_available_counties()
    by_fips: Dict[str, Dict[str, Any]] = {c["county_fips"]: c for c in counties}
    fb_fips = (fallback_fips or DEFAULT_COUNTY_FIPS).strip()
    default_entry = (
        by_fips.get(fb_fips)
        or by_fips.get(DEFAULT_COUNTY_FIPS)
        or (counties[0] if counties else _FALLBACK_COUNTIES[0])
    )

    q_raw = (question or "").strip()
    if not q_raw:
        return {**default_entry, "matched_from_query": False}

    q_lower = q_raw.lower()
    # Normalize punctuation (keep hyphens and spaces clean)
    q_norm = re.sub(r"[^a-z0-9\s\-]", " ", q_lower)
    q_space = re.sub(r"[\-\s]+", " ", q_norm).strip()

    # 1. Check explicit 5-digit FIPS codes or 11-digit Census Tract GEOIDs in question
    for m in re.finditer(r"\b(\d{5})(?:\d{6})?\b", q_lower):
        cand_fips = m.group(1)
        if cand_fips in by_fips:
            return {**by_fips[cand_fips], "matched_from_query": True}

    # Build county name lookup sorted by length descending (e.g. "miami-dade", "palm beach", "santa rosa")
    county_variants: List[tuple[str, Dict[str, Any]]] = []
    for c in counties:
        cname = c["county_name"].lower().strip()
        if cname.endswith(" county"):
            cname = cname[:-7].strip()
        if not cname:
            continue
        county_variants.append((cname, c))
        # Add hyphen/period/saint variations
        no_hyphen = cname.replace("-", " ").replace(".", "").strip()
        no_hyphen = re.sub(r"\s+", " ", no_hyphen)
        if no_hyphen != cname:
            county_variants.append((no_hyphen, c))
        if no_hyphen.startswith("st "):
            county_variants.append(("saint " + no_hyphen[3:], c))
        if cname == "miami-dade":
            county_variants.append(("dade", c))

    county_variants.sort(key=lambda item: len(item[0]), reverse=True)

    # 2a. First check explicit "<county_name> county" mentions
    for cname_var, c_obj in county_variants:
        pattern_explicit = r"\b" + re.escape(cname_var) + r"\s+county\b"
        if re.search(pattern_explicit, q_norm) or re.search(pattern_explicit, q_space):
            return {**c_obj, "matched_from_query": True}

    # 2b. Next check known city names (longer cities first, e.g. "west palm beach" before "palm beach")
    city_cache = _city_to_county_cache or {}
    sorted_cities = sorted(
        [(city_k, c_obj) for city_k, c_obj in city_cache.items() if len(city_k) >= 4],
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for city_name, c_obj in sorted_cities:
        city_clean = re.sub(r"[^a-z0-9\s\-]", " ", city_name.lower())
        city_clean = re.sub(r"[\-\s]+", " ", city_clean).strip()
        if len(city_clean) < 4:
            continue
        if re.search(r"\b" + re.escape(city_clean) + r"\b", q_space):
            return {**c_obj, "matched_from_query": True}

    # 2c. Next check standalone county names (excluding ambiguous common words unless no other context)
    ambiguous_bare = {"union", "liberty", "orange", "lake", "bay", "clay", "gulf", "baker", "franklin", "jackson", "washington", "taylor", "madison", "jefferson", "hamilton", "columbia", "highlands"}
    for cname_var, c_obj in county_variants:
        if len(cname_var) < 3 or cname_var in ambiguous_bare:
            continue
        # Avoid matching "lee boulevard" as a bare county override if another county isn't meant, though Lee Blvd is in Lee County (12071) anyway
        if re.search(r"\b" + re.escape(cname_var) + r"\b", q_norm) or re.search(
            r"\b" + re.escape(cname_var) + r"\b", q_space
        ):
            return {**c_obj, "matched_from_query": True}

    # 2d. Finally check ambiguous bare county names if present as a standalone capitalized/word token
    for cname_var, c_obj in county_variants:
        if cname_var in ambiguous_bare:
            if re.search(r"\b" + re.escape(cname_var) + r"\b", q_space):
                return {**c_obj, "matched_from_query": True}

    return {**default_entry, "matched_from_query": False}


def _bool_to_epistemic_status(val: Optional[bool]) -> str:
    """Convert nullable BOOL column from BigQuery into YES / NO / UNRECORDED."""
    if val is True:
        return "YES"
    if val is False:
        return "NO"
    return "UNRECORDED"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute straight-line distance in kilometers between two WGS84 coordinates."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def audit_county_shelters(
    county_fips: str = DEFAULT_COUNTY_FIPS,
    top_n: int = 12,
) -> Dict[str, Any]:
    """Audit all registered shelters in a county (Option 1: Ghost Shelter & Accessibility Auditor).

    Queries `evacuation_readiness.shelters` and joins to the nearest `hazard_tracts` via
    `ST_DISTANCE` plus any operator field overrides in `shelter_assessments`.
    Explicitly separates TRUE ('YES'), FALSE ('NO'), and NULL ('UNRECORDED') for
    wheelchair_accessible, generator_onsite, self_sufficient_electricity, and in_surge_slosh_area.

    Args:
        county_fips: 5-character county FIPS code (defaults to '12071' for Lee County, FL).
        top_n: Number of highest-capacity shelters to return for live Google Maps Grounding.

    Returns:
        Dictionary with county-wide epistemic gap metrics, data defect alerts, surge-exposed
        shelters, and prioritized candidate shelters for August field inspection.
    """
    bq = get_bq_client()
    t_shelters = f"`{PROJECT_ID}.{DATASET}.shelters`"
    t_hazard = f"`{PROJECT_ID}.{DATASET}.hazard_tracts`"
    t_vtracts = f"`{PROJECT_ID}.{DATASET}.vulnerability_tracts`"
    t_assess = f"`{PROJECT_ID}.{DATASET}.shelter_assessments`"

    summary_sql = f"""
    SELECT
      ANY_VALUE(county_name) AS county_name,
      COUNT(*) AS total_shelters,
      COUNTIF(usage IN ('EVAC', 'BOTH') OR usage IS NULL) AS evac_eligible_shelters,
      COUNTIF(usage = 'POST') AS post_impact_only_shelters,
      SUM(CASE WHEN evacuation_capacity > 0 AND evacuation_capacity <= 100000 THEN evacuation_capacity ELSE 0 END) AS total_plausible_evac_capacity,
      SUM(CASE WHEN post_impact_capacity > 0 AND post_impact_capacity <= 100000 THEN post_impact_capacity ELSE 0 END) AS total_plausible_post_capacity,
      COUNTIF(evacuation_capacity < 0) AS negative_capacity_count,
      COUNTIF(evacuation_capacity > 100000) AS implausible_huge_capacity_count,
      COUNTIF(wheelchair_accessible IS TRUE) AS wc_yes,
      COUNTIF(wheelchair_accessible IS FALSE) AS wc_no,
      COUNTIF(wheelchair_accessible IS NULL) AS wc_unrecorded,
      COUNTIF(generator_onsite IS TRUE) AS gen_yes,
      COUNTIF(generator_onsite IS FALSE) AS gen_no,
      COUNTIF(generator_onsite IS NULL) AS gen_unrecorded,
      COUNTIF(self_sufficient_electricity IS TRUE) AS self_elec_yes,
      COUNTIF(self_sufficient_electricity IS FALSE) AS self_elec_no,
      COUNTIF(self_sufficient_electricity IS NULL) AS self_elec_unrecorded,
      COUNTIF(in_surge_slosh_area IS TRUE) AS surge_yes,
      COUNTIF(in_surge_slosh_area IS FALSE) AS surge_no,
      COUNTIF(in_surge_slosh_area IS NULL) AS surge_unrecorded,
      COUNTIF(in_100_yr_floodplain IS TRUE) AS flood100_yes,
      COUNTIF(in_100_yr_floodplain IS FALSE) AS flood100_no,
      COUNTIF(in_100_yr_floodplain IS NULL) AS flood100_unrecorded,
      COUNTIF(is_medical IS TRUE) AS medical_shelters_yes
    FROM {t_shelters}
    WHERE county_fips = @county_fips
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("county_fips", "STRING", county_fips),
            bigquery.ScalarQueryParameter("top_n", "INT64", int(top_n)),
        ]
    )
    summary_rows = list(bq.query(summary_sql, job_config=job_config).result())
    if not summary_rows or summary_rows[0].total_shelters == 0:
        return {
            "status": "error",
            "message": f"No shelters found for county_fips={county_fips}",
        }
    s = summary_rows[0]
    total = int(s.total_shelters)

    # Pull individual shelters with nearest hazard tract exposure + latest field assessment
    shelters_sql = f"""
    WITH county_shelters AS (
      SELECT
        shelter_id,
        shelter_name,
        address_1,
        city,
        state,
        zip,
        county_fips,
        county_name,
        latitude,
        longitude,
        COALESCE(evacuation_capacity, 0) AS evacuation_capacity,
        COALESCE(post_impact_capacity, 0) AS post_impact_capacity,
        GREATEST(COALESCE(evacuation_capacity, 0), COALESCE(post_impact_capacity, 0)) AS effective_capacity,
        wheelchair_accessible,
        generator_onsite,
        self_sufficient_electricity,
        in_surge_slosh_area,
        in_100_yr_floodplain,
        is_medical,
        is_functional,
        usage,
        shelter_status_code,
        pet_accommodations_code
      FROM {t_shelters}
      WHERE county_fips = @county_fips
    ),
    tract_hazards AS (
      SELECT
        v.geo_id,
        v.lat,
        v.lon,
        h.HRCN_AFREQ,
        h.HRCN_EALT,
        h.CFLD_AFREQ,
        h.CFLD_EALT
      FROM {t_vtracts} v
      JOIN {t_hazard} h USING (geo_id)
      WHERE v.county_fips = @county_fips AND v.lat IS NOT NULL AND v.lon IS NOT NULL
    ),
    nearest_hazard AS (
      SELECT
        cs.shelter_id,
        ARRAY_AGG(
          STRUCT(
            th.geo_id AS nearest_tract_id,
            ROUND(ST_DISTANCE(ST_GEOGPOINT(cs.longitude, cs.latitude), ST_GEOGPOINT(th.lon, th.lat)) / 1000.0, 2) AS tract_dist_km,
            ROUND(th.HRCN_AFREQ, 3) AS hurricane_annual_freq,
            ROUND(th.HRCN_EALT, 0) AS hurricane_expected_annual_loss,
            ROUND(th.CFLD_AFREQ, 3) AS coastal_flood_annual_freq,
            ROUND(th.CFLD_EALT, 0) AS coastal_flood_expected_annual_loss
          )
          ORDER BY ST_DISTANCE(ST_GEOGPOINT(cs.longitude, cs.latitude), ST_GEOGPOINT(th.lon, th.lat)) ASC
          LIMIT 1
        )[OFFSET(0)] AS haz
      FROM county_shelters cs
      CROSS JOIN tract_hazards th
      WHERE cs.latitude IS NOT NULL AND cs.longitude IS NOT NULL
      GROUP BY cs.shelter_id
    ),
    latest_assessment AS (
      SELECT
        shelter_id,
        ARRAY_AGG(
          STRUCT(
            assessed_wheelchair_status,
            operational_status,
            google_maps_place_id,
            inspector_notes,
            CAST(assessed_at AS STRING) AS assessed_at
          )
          ORDER BY assessed_at DESC
          LIMIT 1
        )[OFFSET(0)] AS field_override
      FROM {t_assess}
      GROUP BY shelter_id
    )
    SELECT
      cs.*,
      nh.haz.nearest_tract_id,
      nh.haz.hurricane_annual_freq,
      nh.haz.hurricane_expected_annual_loss,
      nh.haz.coastal_flood_annual_freq,
      nh.haz.coastal_flood_expected_annual_loss,
      la.field_override.assessed_wheelchair_status AS field_assessed_wheelchair_status,
      la.field_override.operational_status AS field_operational_status,
      la.field_override.google_maps_place_id AS saved_place_id,
      la.field_override.inspector_notes AS field_inspector_notes,
      la.field_override.assessed_at AS field_assessed_at
    FROM county_shelters cs
    LEFT JOIN nearest_hazard nh USING (shelter_id)
    LEFT JOIN latest_assessment la USING (shelter_id)
    ORDER BY
      CASE WHEN cs.in_surge_slosh_area IS TRUE THEN 0 ELSE 1 END,
      cs.effective_capacity DESC,
      cs.shelter_name ASC
    """

    try:
        rows = list(bq.query(shelters_sql, job_config=job_config).result())
    except Exception:
        # Fallback if shelter_assessments table does not exist yet
        fallback_sql = shelters_sql.replace(
            f"FROM {t_assess}",
            f"FROM (SELECT CAST(NULL AS INT64) AS shelter_id, CAST(NULL AS STRING) AS assessed_wheelchair_status, CAST(NULL AS STRING) AS operational_status, CAST(NULL AS STRING) AS google_maps_place_id, CAST(NULL AS STRING) AS inspector_notes, CURRENT_TIMESTAMP() AS assessed_at FROM UNNEST([]) )",
        )
        rows = list(bq.query(fallback_sql, job_config=job_config).result())

    all_shelters: List[Dict[str, Any]] = []
    surge_shelters: List[Dict[str, Any]] = []

    for r in rows:
        fema_wc = _bool_to_epistemic_status(r.wheelchair_accessible)
        fema_gen = _bool_to_epistemic_status(r.generator_onsite)
        fema_surge = _bool_to_epistemic_status(r.in_surge_slosh_area)
        fema_flood = _bool_to_epistemic_status(r.in_100_yr_floodplain)

        effective_wc = (
            r.field_assessed_wheelchair_status
            if getattr(r, "field_assessed_wheelchair_status", None)
            else fema_wc
        )

        # Compute pre-season inspection priority score and reason
        reasons: List[str] = []
        if r.in_surge_slosh_area is True:
            reasons.append("CRITICAL: Located inside SLOSH storm-surge zone (in_surge_slosh_area = TRUE)")
        if r.in_100_yr_floodplain is True:
            reasons.append("Located inside 100-year floodplain")
        if fema_wc == "UNRECORDED":
            reasons.append("Wheelchair accessibility UNRECORDED in 2022 FEMA registry")
        if fema_gen == "UNRECORDED":
            reasons.append("Backup generator status UNRECORDED in 2022 FEMA registry")
        if r.usage == "POST":
            reasons.append("Designated POST-impact only (not pre-landfall wind-rated EVAC shelter)")

        item = {
            "shelter_id": int(r.shelter_id),
            "shelter_name": r.shelter_name,
            "address_1": r.address_1,
            "city": r.city,
            "state": r.state,
            "zip": r.zip,
            "latitude": float(r.latitude) if r.latitude is not None else None,
            "longitude": float(r.longitude) if r.longitude is not None else None,
            "evacuation_capacity": int(r.evacuation_capacity or 0),
            "post_impact_capacity": int(r.post_impact_capacity or 0),
            "effective_capacity": int(r.effective_capacity or 0),
            "usage": r.usage or "UNSPECIFIED",
            "shelter_status_code": r.shelter_status_code or "OPEN",
            "is_medical": bool(r.is_medical) if r.is_medical is not None else False,
            "fema_2022_record": {
                "wheelchair_accessible": fema_wc,
                "generator_onsite": fema_gen,
                "self_sufficient_electricity": _bool_to_epistemic_status(
                    r.self_sufficient_electricity
                ),
                "in_surge_slosh_area": fema_surge,
                "in_100_yr_floodplain": fema_flood,
                "provenance": "2022 FEMA National Shelter System (Historical Record)",
            },
            "effective_wheelchair_status": effective_wc,
            "field_assessment": {
                "assessed_wheelchair_status": getattr(
                    r, "field_assessed_wheelchair_status", None
                ),
                "operational_status": getattr(r, "field_operational_status", None),
                "google_maps_place_id": getattr(r, "saved_place_id", None),
                "inspector_notes": getattr(r, "field_inspector_notes", None),
                "assessed_at": getattr(r, "field_assessed_at", None),
            }
            if getattr(r, "field_assessed_wheelchair_status", None)
            else None,
            "hazard_context": {
                "nearest_tract_id": getattr(r, "nearest_tract_id", None),
                "hurricane_annual_freq": getattr(r, "hurricane_annual_freq", None),
                "hurricane_expected_annual_loss_usd": getattr(
                    r, "hurricane_expected_annual_loss", None
                ),
                "coastal_flood_expected_annual_loss_usd": getattr(
                    r, "coastal_flood_expected_annual_loss", None
                ),
            },
            "audit_flags": reasons,
        }
        all_shelters.append(item)
        if r.in_surge_slosh_area is True or r.in_100_yr_floodplain is True:
            surge_shelters.append(item)

    # Sort top candidates by effective_capacity DESC for August triage
    top_candidates = sorted(
        all_shelters,
        key=lambda x: (
            1 if x["fema_2022_record"]["in_surge_slosh_area"] == "YES" else 0,
            x["effective_capacity"],
            1 if x["fema_2022_record"]["wheelchair_accessible"] == "UNRECORDED" else 0,
        ),
        reverse=True,
    )[:top_n]

    # Top 3 physical field inspection priorities for the August Ground-Truth Action List
    august_triage_top3 = sorted(
        all_shelters,
        key=lambda x: (
            x["effective_capacity"]
            if x["fema_2022_record"]["wheelchair_accessible"] == "UNRECORDED"
            or x["fema_2022_record"]["in_surge_slosh_area"] == "YES"
            else -1
        ),
        reverse=True,
    )[:3]

    verified_shelters = sorted(
        [
            x
            for x in all_shelters
            if (
                x["fema_2022_record"]["generator_onsite"] == "YES"
                or x["fema_2022_record"]["wheelchair_accessible"] == "YES"
                or x.get("is_medical") is True
                or x.get("effective_wheelchair_status") == "FIELD_VERIFIED_YES"
            )
            and x["fema_2022_record"]["in_surge_slosh_area"] != "YES"
        ],
        key=lambda x: (1 if x.get("is_medical") else 0, x["effective_capacity"]),
        reverse=True,
    )

    return {
        "status": "ok",
        "county_fips": county_fips,
        "county_name": s.county_name or "Lee",
        "data_provenance": "BigQuery qwiklabs-gcp-03-bb316766e33b.evacuation_readiness.shelters (2022 FEMA NSS + NRI Hazard Tracts)",
        "epistemic_summary": {
            "total_shelters": total,
            "evac_eligible_shelters": int(s.evac_eligible_shelters),
            "post_impact_only_shelters": int(s.post_impact_only_shelters),
            "total_plausible_evac_capacity": int(s.total_plausible_evac_capacity or 0),
            "total_plausible_post_capacity": int(s.total_plausible_post_capacity or 0),
            "wheelchair_accessible": {
                "YES": int(s.wc_yes),
                "NO": int(s.wc_no),
                "UNRECORDED": int(s.wc_unrecorded),
                "pct_unrecorded": round(100.0 * int(s.wc_unrecorded) / max(total, 1), 1),
                "epistemic_warning": (
                    f"{int(s.wc_unrecorded)} of {total} shelters ({round(100.0 * int(s.wc_unrecorded) / max(total, 1), 1)}%) "
                    f"have UNRECORDED wheelchair accessibility. Blank/NULL means nobody wrote it down—never 'NO'."
                ),
            },
            "generator_onsite": {
                "YES": int(s.gen_yes),
                "NO": int(s.gen_no),
                "UNRECORDED": int(s.gen_unrecorded),
                "pct_unrecorded": round(100.0 * int(s.gen_unrecorded) / max(total, 1), 1),
            },
            "in_surge_slosh_area": {
                "YES": int(s.surge_yes),
                "NO": int(s.surge_no),
                "UNRECORDED": int(s.surge_unrecorded),
                "pct_unrecorded": round(100.0 * int(s.surge_unrecorded) / max(total, 1), 1),
            },
            "in_100_yr_floodplain": {
                "YES": int(s.flood100_yes),
                "NO": int(s.flood100_no),
                "UNRECORDED": int(s.flood100_unrecorded),
            },
            "medical_designated_shelters": int(s.medical_shelters_yes),
            "data_defect_checks": {
                "negative_capacity_rows": int(s.negative_capacity_count),
                "implausible_capacity_over_100k_rows": int(s.implausible_huge_capacity_count),
                "ada_compliant_column_ignored": True,
                "ada_compliant_note": "Ignored decoy column `ada_compliant` (63 TRUE nationally); using `wheelchair_accessible`.",
            },
        },
        "surge_or_flood_exposed_shelters": surge_shelters,
        "verified_safe_or_power_shelters": verified_shelters,
        "august_field_inspection_top3": august_triage_top3,
        "top_candidate_shelters": top_candidates,
    }


def find_zero_car_transit_gaps(
    county_fips: str = DEFAULT_COUNTY_FIPS,
    top_n: int = 5,
) -> Dict[str, Any]:
    """Identify the top carless census tracts and calculate distance gaps to non-surge shelters (Option 2).

    Ranks census tracts in `vulnerability_tracts` by `households_no_vehicle` (ACS) and
    `pct_no_vehicle` (CDC SVI), bypassing `pct_lacktrpt` (which is 100% NULL in Florida CDC PLACES).
    Uses BigQuery `ST_DISTANCE` to find:
      1. Nearest shelter not flagged in a SLOSH storm surge zone (`COALESCE(in_surge_slosh_area, FALSE) IS FALSE`)
      2. Nearest confirmed wheelchair-accessible non-surge shelter (`wheelchair_accessible IS TRUE`)
    Flags any tract where the nearest safe shelter is > 2.0 km ("Walkability Wall") and outputs
    T-minus 48-hour municipal bus staging coordinates.

    Args:
        county_fips: 5-character county FIPS code (defaults to '12071' for Lee County, FL).
        top_n: Number of highest no-vehicle tracts to return (defaults to 5).

    Returns:
        Dictionary of top carless census tracts, straight-line distance gaps, Walkability Wall flags,
        and T-minus 48h bus staging coordinates.
    """
    bq = get_bq_client()
    t_vtracts = f"`{PROJECT_ID}.{DATASET}.vulnerability_tracts`"
    t_hazard = f"`{PROJECT_ID}.{DATASET}.hazard_tracts`"
    t_shelters = f"`{PROJECT_ID}.{DATASET}.shelters`"

    sql = f"""
    WITH tracts AS (
      SELECT
        v.geo_id,
        v.county_fips,
        v.total_pop,
        v.households,
        v.households_no_vehicle,
        ROUND(v.pct_no_vehicle, 1) AS pct_no_vehicle,
        ROUND(v.pct_disability, 1) AS pct_disability,
        ROUND(v.pct_age_65_plus, 1) AS pct_age_65_plus,
        ROUND(v.pct_mobility, 1) AS pct_mobility,
        ROUND(v.pct_selfcare, 1) AS pct_selfcare,
        v.pct_lacktrpt,
        ROUND(v.mobile_homes, 0) AS mobile_homes,
        ROUND(v.poverty_rate * 100.0, 1) AS poverty_rate_pct,
        v.lat,
        v.lon,
        ROUND(h.HRCN_AFREQ, 3) AS hrcn_afreq,
        ROUND(h.HRCN_EALT, 0) AS hrcn_ealt,
        ROUND(h.CFLD_EALT, 0) AS cfld_ealt
      FROM {t_vtracts} v
      LEFT JOIN {t_hazard} h USING (geo_id)
      WHERE v.county_fips = @county_fips
        AND v.lat IS NOT NULL
        AND v.lon IS NOT NULL
        AND COALESCE(v.households_no_vehicle, 0) > 0
      ORDER BY v.households_no_vehicle DESC, v.pct_no_vehicle DESC
      LIMIT @top_n
    ),
    shelters AS (
      SELECT
        shelter_id,
        shelter_name,
        address_1,
        city,
        state,
        zip,
        latitude,
        longitude,
        GREATEST(COALESCE(evacuation_capacity, 0), COALESCE(post_impact_capacity, 0)) AS effective_capacity,
        wheelchair_accessible,
        generator_onsite,
        in_surge_slosh_area,
        usage
      FROM {t_shelters}
      WHERE county_fips = @county_fips
        AND latitude IS NOT NULL
        AND longitude IS NOT NULL
    ),
    pairs AS (
      SELECT
        t.*,
        s.shelter_id,
        s.shelter_name,
        s.address_1,
        s.city,
        s.state,
        s.zip,
        s.latitude AS shelter_lat,
        s.longitude AS shelter_lon,
        s.effective_capacity,
        s.wheelchair_accessible,
        s.generator_onsite,
        s.in_surge_slosh_area,
        s.usage,
        ST_DISTANCE(ST_GEOGPOINT(t.lon, t.lat), ST_GEOGPOINT(s.longitude, s.latitude)) / 1000.0 AS dist_km
      FROM tracts t
      CROSS JOIN shelters s
    )
    SELECT
      geo_id,
      ANY_VALUE(total_pop) AS total_pop,
      ANY_VALUE(households) AS households,
      ANY_VALUE(households_no_vehicle) AS households_no_vehicle,
      ANY_VALUE(pct_no_vehicle) AS pct_no_vehicle,
      ANY_VALUE(pct_disability) AS pct_disability,
      ANY_VALUE(pct_age_65_plus) AS pct_age_65_plus,
      ANY_VALUE(pct_mobility) AS pct_mobility,
      ANY_VALUE(mobile_homes) AS mobile_homes,
      ANY_VALUE(poverty_rate_pct) AS poverty_rate_pct,
      ANY_VALUE(lat) AS tract_lat,
      ANY_VALUE(lon) AS tract_lon,
      ANY_VALUE(hrcn_ealt) AS hurricane_expected_annual_loss_usd,
      ANY_VALUE(cfld_ealt) AS coastal_flood_expected_annual_loss_usd,
      COUNTIF(dist_km <= 5.0 AND COALESCE(in_surge_slosh_area, FALSE) IS FALSE) AS non_surge_shelters_within_5km,
      COUNTIF(dist_km <= 5.0 AND wheelchair_accessible IS TRUE AND COALESCE(in_surge_slosh_area, FALSE) IS FALSE) AS wc_yes_shelters_within_5km,
      COUNTIF(dist_km <= 5.0 AND wheelchair_accessible IS NULL AND COALESCE(in_surge_slosh_area, FALSE) IS FALSE) AS wc_unrecorded_shelters_within_5km,
      ARRAY_AGG(
        IF(COALESCE(in_surge_slosh_area, FALSE) IS FALSE,
          STRUCT(
            shelter_id,
            shelter_name,
            address_1,
            city,
            state,
            zip,
            shelter_lat,
            shelter_lon,
            effective_capacity,
            wheelchair_accessible,
            generator_onsite,
            ROUND(dist_km, 2) AS dist_km
          ),
          NULL
        ) IGNORE NULLS
        ORDER BY dist_km ASC
        LIMIT 1
      )[SAFE_OFFSET(0)] AS nearest_non_surge_shelter,
      ARRAY_AGG(
        IF(wheelchair_accessible IS TRUE AND COALESCE(in_surge_slosh_area, FALSE) IS FALSE,
          STRUCT(
            shelter_id,
            shelter_name,
            address_1,
            city,
            state,
            zip,
            shelter_lat,
            shelter_lon,
            effective_capacity,
            ROUND(dist_km, 2) AS dist_km
          ),
          NULL
        ) IGNORE NULLS
        ORDER BY dist_km ASC
        LIMIT 1
      )[SAFE_OFFSET(0)] AS nearest_wc_confirmed_shelter
    FROM pairs
    GROUP BY geo_id
    ORDER BY households_no_vehicle DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("county_fips", "STRING", county_fips),
            bigquery.ScalarQueryParameter("top_n", "INT64", int(top_n)),
        ]
    )
    rows = list(bq.query(sql, job_config=job_config).result())

    tracts_out: List[Dict[str, Any]] = []
    total_no_vehicle_hh = 0

    for idx, r in enumerate(rows, start=1):
        hh_no_veh = int(r.households_no_vehicle or 0)
        total_no_vehicle_hh += hh_no_veh
        ns = r.nearest_non_surge_shelter
        wc_s = r.nearest_wc_confirmed_shelter

        ns_dist_km = float(ns["dist_km"]) if ns and ns["dist_km"] is not None else None
        wc_dist_km = float(wc_s["dist_km"]) if wc_s and wc_s["dist_km"] is not None else None
        walkability_wall_any = ns_dist_km is not None and ns_dist_km > 2.0
        walkability_wall_wc = wc_dist_km is not None and wc_dist_km > 2.0

        # Estimate buses needed assuming ~40 evacuees per municipal transit bus
        est_carless_residents = int(round(hh_no_veh * 2.1))
        buses_recommended = max(2, int(math.ceil(est_carless_residents / 120.0)))

        tracts_out.append(
            {
                "rank": idx,
                "geo_id": r.geo_id,
                "total_pop": int(r.total_pop or 0),
                "households": int(r.households or 0),
                "households_no_vehicle": hh_no_veh,
                "pct_no_vehicle": float(r.pct_no_vehicle or 0.0),
                "pct_disability": float(r.pct_disability or 0.0),
                "pct_age_65_plus": float(r.pct_age_65_plus or 0.0),
                "pct_mobility_difficulty": float(r.pct_mobility or 0.0),
                "mobile_homes": int(r.mobile_homes or 0),
                "poverty_rate_pct": float(r.poverty_rate_pct or 0.0),
                "pickup_staging_coordinates": {
                    "lat": round(float(r.tract_lat), 5),
                    "lon": round(float(r.tract_lon), 5),
                    "staging_window": "T-minus 48h to T-minus 24h before tropical-storm-force winds",
                    "recommended_municipal_buses": buses_recommended,
                },
                "nearest_non_surge_shelter": {
                    "shelter_id": int(ns["shelter_id"]),
                    "shelter_name": ns["shelter_name"],
                    "address_1": ns["address_1"],
                    "city": ns["city"],
                    "state": ns["state"],
                    "zip": ns["zip"],
                    "latitude": float(ns["shelter_lat"]),
                    "longitude": float(ns["shelter_lon"]),
                    "straight_line_distance_km": ns_dist_km,
                    "distance_type": "straight-line (BigQuery ST_DISTANCE)",
                    "fema_wheelchair_accessible": _bool_to_epistemic_status(
                        ns["wheelchair_accessible"]
                    ),
                    "fema_generator_onsite": _bool_to_epistemic_status(
                        ns["generator_onsite"]
                    ),
                }
                if ns
                else None,
                "nearest_confirmed_wheelchair_shelter": {
                    "shelter_id": int(wc_s["shelter_id"]),
                    "shelter_name": wc_s["shelter_name"],
                    "address_1": wc_s["address_1"],
                    "city": wc_s["city"],
                    "state": wc_s["state"],
                    "zip": wc_s["zip"],
                    "straight_line_distance_km": wc_dist_km,
                    "distance_type": "straight-line (BigQuery ST_DISTANCE)",
                }
                if wc_s
                else None,
                "shelters_within_5km_breakdown": {
                    "non_surge_total": int(r.non_surge_shelters_within_5km),
                    "wheelchair_confirmed_yes": int(r.wc_yes_shelters_within_5km),
                    "wheelchair_unrecorded": int(r.wc_unrecorded_shelters_within_5km),
                },
                "walkability_wall_exceeded_any_shelter": walkability_wall_any,
                "walkability_wall_exceeded_wc_shelter": walkability_wall_wc,
                "walkability_status": (
                    f"WALKABILITY WALL EXCEEDED ({ns_dist_km} km straight-line to nearest non-surge shelter; "
                    f"{wc_dist_km} km to nearest confirmed wheelchair-accessible shelter)"
                    if walkability_wall_any
                    else f"Within 2.0 km straight-line to nearest shelter ({ns_dist_km} km), but {wc_dist_km} km to confirmed wheelchair-accessible shelter"
                ),
            }
        )

    return {
        "status": "ok",
        "county_fips": county_fips,
        "data_defect_disclosure": (
            "CDC PLACES `pct_lacktrpt` (transportation barriers) is 100% NULL in Florida. "
            "Ranking uses ACS `households_no_vehicle` and CDC SVI `pct_no_vehicle`, which measure "
            "household vehicle ownership rather than broader transit ride-dependency."
        ),
        "distance_methodology_note": (
            "Distances in this table are straight-line (`ST_DISTANCE` in km). Call "
            "`verify_place_with_maps_grounding` with `origin_lat` and `origin_lon` to obtain "
            "live Google Maps road routing distance and travel times across bridges/canals."
        ),
        "total_carless_households_in_top_tracts": total_no_vehicle_hh,
        "priority_zero_car_tracts": tracts_out,
    }


def check_medical_power_gaps(
    county_fips: str = DEFAULT_COUNTY_FIPS,
    top_n: int = 8,
) -> Dict[str, Any]:
    """Cross-reference nursing homes and county power-dependent Medicare residents against shelter backup generators (Option 3).

    Enforces two critical Challenge 4 guardrails:
      1. County-scale guardrail: HHS emPOWER (`power_dependent_counties`) is strictly county-level
         and is NEVER disaggregated down to individual census tracts.
      2. Censored-value guardrail: Checks `power_dependent_is_censored` (where counts of 1-10 are
         masked as `11` by HIPAA suppression rules).

    Args:
        county_fips: 5-character county FIPS code (defaults to '12071' for Lee County, FL).
        top_n: Number of largest CMS nursing homes (by certified beds) to return.

    Returns:
        Dictionary with county-level emPOWER electricity-dependent resident metrics, shelter backup
        generator coverage, and top CMS nursing homes with their nearest generator-confirmed vs.
        generator-unrecorded shelters.
    """
    bq = get_bq_client()
    t_empower = f"`{PROJECT_ID}.{DATASET}.power_dependent_counties`"
    t_care = f"`{PROJECT_ID}.{DATASET}.care_facilities`"
    t_shelters = f"`{PROJECT_ID}.{DATASET}.shelters`"
    t_vtracts = f"`{PROJECT_ID}.{DATASET}.vulnerability_tracts`"

    empower_sql = f"""
    SELECT
      fips_code,
      county,
      medicare_benes,
      power_dependent_dme,
      power_dependent_is_censored,
      o2_services_any_dme,
      facility_esrd_dialysis_any_dme,
      home_health_services_any_dme,
      athome_hospice_any_dme
    FROM {t_empower}
    WHERE fips_code = @county_fips
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("county_fips", "STRING", county_fips),
            bigquery.ScalarQueryParameter("top_n", "INT64", int(top_n)),
        ]
    )
    emp_rows = list(bq.query(empower_sql, job_config=job_config).result())
    emp = emp_rows[0] if emp_rows else None

    # Match nursing homes to the county via nearest census tract county_fips
    care_sql = f"""
    WITH facility_county AS (
      SELECT
        cf.cms_certification_number_ccn,
        cf.provider_name,
        cf.provider_address,
        cf.citytown,
        cf.state,
        cf.zip_code,
        COALESCE(cf.number_of_certified_beds, 0) AS certified_beds,
        cf.ownership_type,
        cf.latitude,
        cf.longitude,
        ARRAY_AGG(v.county_fips ORDER BY ST_DISTANCE(ST_GEOGPOINT(cf.longitude, cf.latitude), ST_GEOGPOINT(v.lon, v.lat)) ASC LIMIT 1)[OFFSET(0)] AS inferred_county_fips
      FROM {t_care} cf
      CROSS JOIN {t_vtracts} v
      WHERE cf.latitude IS NOT NULL AND cf.longitude IS NOT NULL
        AND v.lat IS NOT NULL AND v.lon IS NOT NULL
      GROUP BY
        cf.cms_certification_number_ccn,
        cf.provider_name,
        cf.provider_address,
        cf.citytown,
        cf.state,
        cf.zip_code,
        cf.number_of_certified_beds,
        cf.ownership_type,
        cf.latitude,
        cf.longitude
    ),
    county_care AS (
      SELECT *
      FROM facility_county
      WHERE inferred_county_fips = @county_fips
    ),
    county_shelters AS (
      SELECT
        shelter_id,
        shelter_name,
        address_1,
        city,
        latitude,
        longitude,
        GREATEST(COALESCE(evacuation_capacity, 0), COALESCE(post_impact_capacity, 0)) AS effective_capacity,
        generator_onsite,
        self_sufficient_electricity,
        wheelchair_accessible,
        is_medical,
        in_surge_slosh_area
      FROM {t_shelters}
      WHERE county_fips = @county_fips
        AND latitude IS NOT NULL AND longitude IS NOT NULL
    )
    SELECT
      cc.cms_certification_number_ccn,
      cc.provider_name,
      cc.provider_address,
      cc.citytown,
      cc.state,
      cc.zip_code,
      cc.certified_beds,
      cc.ownership_type,
      cc.latitude,
      cc.longitude,
      COUNTIF(ST_DISTANCE(ST_GEOGPOINT(cc.longitude, cc.latitude), ST_GEOGPOINT(cs.longitude, cs.latitude)) <= 10000 AND COALESCE(cs.in_surge_slosh_area, FALSE) IS FALSE) AS shelters_within_10km_total,
      COUNTIF(ST_DISTANCE(ST_GEOGPOINT(cc.longitude, cc.latitude), ST_GEOGPOINT(cs.longitude, cs.latitude)) <= 10000 AND cs.generator_onsite IS TRUE AND COALESCE(cs.in_surge_slosh_area, FALSE) IS FALSE) AS shelters_within_10km_gen_yes,
      COUNTIF(ST_DISTANCE(ST_GEOGPOINT(cc.longitude, cc.latitude), ST_GEOGPOINT(cs.longitude, cs.latitude)) <= 10000 AND cs.generator_onsite IS NULL AND COALESCE(cs.in_surge_slosh_area, FALSE) IS FALSE) AS shelters_within_10km_gen_unrecorded,
      COUNTIF(ST_DISTANCE(ST_GEOGPOINT(cc.longitude, cc.latitude), ST_GEOGPOINT(cs.longitude, cs.latitude)) <= 10000 AND cs.is_medical IS TRUE) AS medical_shelters_within_10km,
      ARRAY_AGG(
        IF(cs.generator_onsite IS TRUE AND COALESCE(cs.in_surge_slosh_area, FALSE) IS FALSE,
          STRUCT(
            cs.shelter_id,
            cs.shelter_name,
            cs.address_1,
            cs.city,
            cs.latitude AS shelter_lat,
            cs.longitude AS shelter_lon,
            cs.effective_capacity,
            cs.is_medical,
            cs.wheelchair_accessible,
            ROUND(ST_DISTANCE(ST_GEOGPOINT(cc.longitude, cc.latitude), ST_GEOGPOINT(cs.longitude, cs.latitude)) / 1000.0, 2) AS dist_km
          ),
          NULL
        ) IGNORE NULLS
        ORDER BY ST_DISTANCE(ST_GEOGPOINT(cc.longitude, cc.latitude), ST_GEOGPOINT(cs.longitude, cs.latitude)) ASC
        LIMIT 1
      )[SAFE_OFFSET(0)] AS nearest_generator_confirmed_shelter,
      ARRAY_AGG(
        IF(COALESCE(cs.in_surge_slosh_area, FALSE) IS FALSE,
          STRUCT(
            cs.shelter_id,
            cs.shelter_name,
            cs.address_1,
            cs.city,
            cs.latitude AS shelter_lat,
            cs.longitude AS shelter_lon,
            cs.effective_capacity,
            cs.generator_onsite,
            cs.is_medical,
            ROUND(ST_DISTANCE(ST_GEOGPOINT(cc.longitude, cc.latitude), ST_GEOGPOINT(cs.longitude, cs.latitude)) / 1000.0, 2) AS dist_km
          ),
          NULL
        ) IGNORE NULLS
        ORDER BY ST_DISTANCE(ST_GEOGPOINT(cc.longitude, cc.latitude), ST_GEOGPOINT(cs.longitude, cs.latitude)) ASC
        LIMIT 1
      )[SAFE_OFFSET(0)] AS nearest_any_non_surge_shelter
    FROM county_care cc
    CROSS JOIN county_shelters cs
    GROUP BY
      cc.cms_certification_number_ccn,
      cc.provider_name,
      cc.provider_address,
      cc.citytown,
      cc.state,
      cc.zip_code,
      cc.certified_beds,
      cc.ownership_type,
      cc.latitude,
      cc.longitude
    ORDER BY cc.certified_beds DESC
    """
    all_care_rows = list(bq.query(care_sql, job_config=job_config).result())
    total_facilities = len(all_care_rows)
    total_beds = sum(int(r.certified_beds or 0) for r in all_care_rows)

    facilities_out: List[Dict[str, Any]] = []
    for r in all_care_rows[:top_n]:
        gen_s = r.nearest_generator_confirmed_shelter
        any_s = r.nearest_any_non_surge_shelter
        facilities_out.append(
            {
                "cms_ccn": r.cms_certification_number_ccn,
                "provider_name": r.provider_name,
                "provider_address": r.provider_address,
                "city": r.citytown,
                "state": r.state,
                "zip_code": r.zip_code,
                "certified_beds": int(r.certified_beds or 0),
                "ownership_type": r.ownership_type,
                "latitude": float(r.latitude),
                "longitude": float(r.longitude),
                "surrounding_10km_shelters": {
                    "total_non_surge": int(r.shelters_within_10km_total),
                    "generator_confirmed_yes": int(r.shelters_within_10km_gen_yes),
                    "generator_unrecorded": int(r.shelters_within_10km_gen_unrecorded),
                    "medical_designated": int(r.medical_shelters_within_10km),
                },
                "nearest_generator_confirmed_shelter": {
                    "shelter_id": int(gen_s["shelter_id"]),
                    "shelter_name": gen_s["shelter_name"],
                    "address_1": gen_s["address_1"],
                    "city": gen_s["city"],
                    "latitude": float(gen_s["shelter_lat"])
                    if gen_s.get("shelter_lat") is not None
                    else None,
                    "longitude": float(gen_s["shelter_lon"])
                    if gen_s.get("shelter_lon") is not None
                    else None,
                    "effective_capacity": int(gen_s["effective_capacity"] or 0),
                    "is_medical": bool(gen_s["is_medical"])
                    if gen_s["is_medical"] is not None
                    else False,
                    "wheelchair_accessible": _bool_to_epistemic_status(
                        gen_s["wheelchair_accessible"]
                    ),
                    "straight_line_distance_km": float(gen_s["dist_km"]),
                }
                if gen_s
                else None,
                "nearest_any_non_surge_shelter": {
                    "shelter_id": int(any_s["shelter_id"]),
                    "shelter_name": any_s["shelter_name"],
                    "address_1": any_s["address_1"],
                    "city": any_s["city"],
                    "latitude": float(any_s["shelter_lat"])
                    if any_s.get("shelter_lat") is not None
                    else None,
                    "longitude": float(any_s["shelter_lon"])
                    if any_s.get("shelter_lon") is not None
                    else None,
                    "generator_status": _bool_to_epistemic_status(
                        any_s["generator_onsite"]
                    ),
                    "straight_line_distance_km": float(any_s["dist_km"]),
                }
                if any_s
                else None,
            }
        )

    is_censored = bool(emp.power_dependent_is_censored) if emp else False
    dme_val = int(emp.power_dependent_dme or 0) if emp else 0
    emp_county_name = (emp.county if emp and emp.county else "Lee").strip()

    return {
        "status": "ok",
        "county_fips": county_fips,
        "county_name": emp_county_name,
        "empower_county_level_metrics": {
            "granularity_guardrail": (
                "COUNTY-LEVEL ONLY (HHS emPOWER). Never disaggregate or allocate these counts "
                "down to individual census tracts."
            ),
            "medicare_beneficiaries": int(emp.medicare_benes or 0) if emp else 0,
            "power_dependent_dme_beneficiaries": (
                "1-10 (censored as 11 by HIPAA small-number suppression)"
                if is_censored
                else dme_val
            ),
            "power_dependent_raw_value": dme_val,
            "power_dependent_is_censored": is_censored,
            "censoring_note": (
                "Value is exactly 11, which is the HHS emPOWER HIPAA suppression sentinel for 1-10 claims."
                if is_censored
                else f"Uncensored county measurement ({dme_val:,} Medicare beneficiaries relying on electricity-dependent DME)."
            ),
            "oxygen_services_dme": int(emp.o2_services_any_dme or 0) if emp else 0,
            "dialysis_esrd_dme": int(emp.facility_esrd_dialysis_any_dme or 0)
            if emp
            else 0,
            "home_health_dme": int(emp.home_health_services_any_dme or 0) if emp else 0,
            "athome_hospice_dme": int(emp.athome_hospice_any_dme or 0) if emp else 0,
        },
        "cms_nursing_home_summary": {
            "total_nursing_homes_in_county": total_facilities,
            "total_certified_nursing_home_beds": total_beds,
            "mutual_aid_action_required": (
                f"{total_facilities} CMS-certified nursing homes ({total_beds:,} beds) and "
                f"{dme_val:,} home-based electricity-dependent Medicare beneficiaries in {emp_county_name} County "
                f"require verified backup generator shelters before hurricane landfall. Execute pre-season "
                f"generator verification and clinical mutual-aid transfer agreements before September."
            ),
        },
        "top_nursing_homes": facilities_out,
    }


def verify_place_with_maps_grounding(
    place_name: str,
    address: str,
    city: str = "Fort Myers",
    state: str = "FL",
    origin_lat: Optional[float] = None,
    origin_lon: Optional[float] = None,
    origin_label: str = "",
) -> Dict[str, Any]:
    """Verify a single shelter or care facility live using Grounding with Google Maps (and optional Routing).

    Follows the Challenge 4 golden rule:
      - Queries ONE building name + ONE street address at a time (never a county-wide fishing query).
      - Detects whether the facility still exists at that address, has been renamed (same address,
        different current name), or is listed as closed.
      - When `origin_lat` and `origin_lon` are supplied, asks Google Maps Grounding to estimate
        real-world road driving and walking travel times from that origin to the facility.
      - Extracts `grounding_chunks[].maps` (`place_id`, `title`, `uri`) and formats mandatory
        `<span translate="no">Google Maps</span>` inline source attributions.
      - Complies with Google Maps Terms of Service: only `place_id` is retained as a pointer.

    Args:
        place_name: Recorded name of the shelter or care facility from the 2022 FEMA/CMS database.
        address: Street address of the facility.
        city: City name (e.g. 'Fort Myers', 'Cape Coral', 'Lehigh Acres').
        state: Two-letter state code (defaults to 'FL').
        origin_lat: Optional latitude of an evacuation origin (e.g. carless tract centroid).
        origin_lon: Optional longitude of an evacuation origin.
        origin_label: Optional label for the origin (e.g. 'Census Tract 12071000600').

    Returns:
        Dictionary containing the live grounded verification summary, rename/closure detection,
        optional route travel time, `grounding_chunks` (`place_id`, `title`, `uri`), and
        ready-to-render HTML/Markdown attribution with `<span translate="no">Google Maps</span>`.
    """
    client = get_genai_client()
    full_address = f"{address}, {city}, {state}".strip(", ")

    routing_clause = ""
    if origin_lat is not None and origin_lon is not None:
        routing_clause = (
            f"\n4. Routing & Access Context: Describe the road access to {full_address} from "
            f"({origin_lat:.5f}, {origin_lon:.5f}) {f'({origin_label})' if origin_label else ''}, "
            f"including major highways/arterials (e.g., US-41, I-75, SR-82, Caloosahatchee River bridges) "
            f"and approximate driving distance/time if available."
        )

    prompt = (
        f"Verify this specific facility for an August county hurricane preparedness audit:\n"
        f"Recorded Facility Name (2022 Federal Registry): {place_name}\n"
        f"Street Address: {full_address}\n\n"
        f"Check Google Maps for this exact street address and answer concisely:\n"
        f"1. Current Facility Name at Address: What institution or business currently occupies {full_address}?\n"
        f"2. Name Comparison: Does the current name on Google Maps match '{place_name}', or does the building now operate under a different name?\n"
        f"3. Operational Status: Is the facility currently open and operational?"
        f"{routing_clause}\n"
        f"On the final line of your response, output exactly one of these tags:\n"
        f"VERIFICATION_TAG: LIVE_GROUNDED_ACTIVE\n"
        f"VERIFICATION_TAG: VERIFIED_RENAMED\n"
        f"VERIFICATION_TAG: FLAGGED_CLOSED"
    )

    maps_tool = types.Tool(google_maps=types.GoogleMaps())
    tool_cfg = None
    if origin_lat is not None and origin_lon is not None:
        tool_cfg = types.ToolConfig(
            retrieval_config=types.RetrievalConfig(
                lat_lng=types.LatLng(latitude=float(origin_lat), longitude=float(origin_lon))
            )
        )
    used_model = MODEL_NAME

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[maps_tool],
                tool_config=tool_cfg,
                temperature=0.1,
            ),
        )
    except Exception:
        used_model = FALLBACK_MODEL_NAME
        response = client.models.generate_content(
            model=FALLBACK_MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[maps_tool],
                tool_config=tool_cfg,
                temperature=0.1,
            ),
        )

    text = response.text or ""
    gm = (
        response.candidates[0].grounding_metadata
        if response.candidates and response.candidates[0].grounding_metadata
        else None
    )
    raw_chunks = (gm.grounding_chunks if gm and gm.grounding_chunks else []) or []

    sources: List[Dict[str, str]] = []
    seen_uris = set()
    for ch in raw_chunks:
        maps_obj = getattr(ch, "maps", None)
        if maps_obj:
            uri = getattr(maps_obj, "uri", "") or ""
            title = getattr(maps_obj, "title", "") or place_name
            place_id = getattr(maps_obj, "place_id", "") or ""
            if uri not in seen_uris:
                seen_uris.add(uri)
                sources.append(
                    {
                        "title": title,
                        "uri": uri,
                        "place_id": place_id,
                    }
                )

    # Parse structured tag and compare grounded Maps title against recorded 2022 name
    is_closed = "VERIFICATION_TAG: FLAGGED_CLOSED" in text
    is_renamed = "VERIFICATION_TAG: VERIFIED_RENAMED" in text
    if sources:
        top_title = sources[0]["title"].lower().replace(" - google maps", "").strip()
        rec_tokens = {
            w
            for w in place_name.lower().replace("-", " ").split()
            if len(w) > 3
            and w
            not in {
                "school",
                "high",
                "middle",
                "elementary",
                "academy",
                "center",
                "county",
                "fort",
                "myers",
                "north",
                "south",
                "east",
                "west",
                "rehabilitation",
                "healthcare",
                "health",
                "care",
                "nursing",
            }
        }
        if rec_tokens and not any(t in top_title for t in rec_tokens):
            is_renamed = True

    # Strip the machine tag line from user-facing findings text
    clean_lines = [
        line
        for line in text.splitlines()
        if not line.strip().startswith("VERIFICATION_TAG:")
    ]
    clean_text = "\n".join(clean_lines).strip()

    if is_closed:
        verification_badge = "FLAGGED_CLOSED"
    elif is_renamed:
        verification_badge = "VERIFIED_RENAMED"
    elif sources:
        verification_badge = "LIVE_GROUNDED_ACTIVE"
    else:
        verification_badge = "GROUNDED_CHECK_COMPLETED"

    # Build mandatory compliant attribution HTML & Markdown immediately following the content
    if sources:
        links_html = ", ".join(
            f'<a href="{html.escape(src["uri"])}" target="_blank" rel="noopener noreferrer">{html.escape(src["title"])}</a>'
            for src in sources
        )
        attribution_html = (
            f'Source: <span translate="no">Google Maps</span> ({links_html})'
        )
        links_md = ", ".join(f'[{src["title"]}]({src["uri"]})' for src in sources)
        attribution_markdown = (
            f'Source: <span translate="no">Google Maps</span> ({links_md})'
        )
    else:
        attribution_html = 'Source: <span translate="no">Google Maps</span>'
        attribution_markdown = 'Source: <span translate="no">Google Maps</span>'

    return {
        "status": "ok",
        "recorded_name": place_name,
        "queried_address": full_address,
        "model_used": used_model,
        "verification_badge": verification_badge,
        "is_renamed": is_renamed,
        "is_closed": is_closed,
        "grounded_findings": clean_text,
        "google_maps_sources": sources,
        "primary_place_id": sources[0]["place_id"] if sources else None,
        "attribution_html": attribution_html,
        "attribution_markdown": attribution_markdown,
        "provenance_label": "Live Grounded via Grounding with Google Maps (seconds ago)",
    }


def run_equity_audit(county_fips: str = DEFAULT_COUNTY_FIPS) -> Dict[str, Any]:
    """Run a post-hoc fairness and clerical paperwork bias audit on county evacuation readiness.

    Validates two critical equity questions without using race/ethnicity or income as an input
    filter to deprioritize communities:
      1. Do census tracts with higher poverty, disability, or limited English proficiency face
         longer distances to confirmed wheelchair-accessible shelters or higher rates of
         `UNRECORDED` shelter paperwork nearby?
      2. Are high-SVI / high-minority tracts (from `equity_audit_svi_theme3` or `svi_socioeconomic`)
         proportionally represented in our Zero-Car Transit Lifeline bus staging recommendations?

    Args:
        county_fips: 5-character county FIPS code (defaults to '12071' for Lee County, FL).

    Returns:
        Dictionary summarizing the post-hoc demographic and paperwork bias audit.
    """
    bq = get_bq_client()
    t_vtracts = f"`{PROJECT_ID}.{DATASET}.vulnerability_tracts`"
    t_shelters = f"`{PROJECT_ID}.{DATASET}.shelters`"
    t_theme3 = f"`{PROJECT_ID}.{DATASET}.equity_audit_svi_theme3`"

    sql = f"""
    WITH tracts AS (
      SELECT
        v.geo_id,
        v.total_pop,
        v.households_no_vehicle,
        v.pct_no_vehicle,
        v.pct_disability,
        v.pct_limited_english,
        v.poverty_rate,
        v.median_income,
        v.svi_socioeconomic,
        v.svi_household,
        v.svi_housing_transport,
        v.lat,
        v.lon
      FROM {t_vtracts} v
      WHERE v.county_fips = @county_fips
        AND v.lat IS NOT NULL AND v.lon IS NOT NULL
    ),
    shelters AS (
      SELECT
        shelter_id,
        latitude,
        longitude,
        wheelchair_accessible,
        generator_onsite,
        in_surge_slosh_area
      FROM {t_shelters}
      WHERE county_fips = @county_fips
        AND latitude IS NOT NULL AND longitude IS NOT NULL
        AND COALESCE(in_surge_slosh_area, FALSE) IS FALSE
    ),
    tract_shelter_stats AS (
      SELECT
        t.geo_id,
        ANY_VALUE(t.total_pop) AS total_pop,
        ANY_VALUE(t.households_no_vehicle) AS households_no_vehicle,
        ANY_VALUE(t.pct_disability) AS pct_disability,
        ANY_VALUE(t.pct_limited_english) AS pct_limited_english,
        ANY_VALUE(t.poverty_rate) AS poverty_rate,
        ANY_VALUE(t.median_income) AS median_income,
        ANY_VALUE(t.svi_socioeconomic) AS svi_socioeconomic,
        MIN(ST_DISTANCE(ST_GEOGPOINT(t.lon, t.lat), ST_GEOGPOINT(s.longitude, s.latitude)) / 1000.0) AS min_any_shelter_km,
        MIN(IF(s.wheelchair_accessible IS TRUE, ST_DISTANCE(ST_GEOGPOINT(t.lon, t.lat), ST_GEOGPOINT(s.longitude, s.latitude)) / 1000.0, NULL)) AS min_wc_yes_shelter_km,
        COUNTIF(ST_DISTANCE(ST_GEOGPOINT(t.lon, t.lat), ST_GEOGPOINT(s.longitude, s.latitude)) <= 5000 AND s.wheelchair_accessible IS NULL) AS unrecorded_wc_within_5km,
        COUNTIF(ST_DISTANCE(ST_GEOGPOINT(t.lon, t.lat), ST_GEOGPOINT(s.longitude, s.latitude)) <= 5000) AS total_shelters_within_5km
      FROM tracts t
      CROSS JOIN shelters s
      GROUP BY t.geo_id
    )
    SELECT
      CASE
        WHEN svi_socioeconomic >= 0.75 THEN 'High Socioeconomic Vulnerability (Top Quartile SVI >= 0.75)'
        WHEN svi_socioeconomic >= 0.50 THEN 'Moderate-High Vulnerability (0.50 - 0.74)'
        ELSE 'Lower Socioeconomic Vulnerability (< 0.50)'
      END AS vulnerability_tier,
      COUNT(*) AS tract_count,
      SUM(CAST(COALESCE(total_pop, 0) AS INT64)) AS total_population,
      SUM(CAST(COALESCE(households_no_vehicle, 0) AS INT64)) AS carless_households,
      ROUND(AVG(poverty_rate * 100.0), 1) AS avg_poverty_rate_pct,
      ROUND(AVG(pct_disability), 1) AS avg_disability_pct,
      ROUND(AVG(pct_limited_english), 1) AS avg_limited_english_pct,
      ROUND(AVG(min_any_shelter_km), 2) AS avg_dist_any_shelter_km,
      ROUND(AVG(min_wc_yes_shelter_km), 2) AS avg_dist_wc_confirmed_shelter_km,
      ROUND(AVG(SAFE_DIVIDE(unrecorded_wc_within_5km, NULLIF(total_shelters_within_5km, 0)) * 100.0), 1) AS avg_pct_nearby_shelters_unrecorded
    FROM tract_shelter_stats
    WHERE svi_socioeconomic IS NOT NULL
    GROUP BY vulnerability_tier
    ORDER BY avg_poverty_rate_pct DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("county_fips", "STRING", county_fips),
        ]
    )
    rows = list(bq.query(sql, job_config=job_config).result())
    tiers = [
        {
            "vulnerability_tier": r.vulnerability_tier,
            "tract_count": int(r.tract_count),
            "total_population": int(r.total_population or 0),
            "carless_households": int(r.carless_households or 0),
            "avg_poverty_rate_pct": float(r.avg_poverty_rate_pct or 0.0),
            "avg_disability_pct": float(r.avg_disability_pct or 0.0),
            "avg_limited_english_pct": float(r.avg_limited_english_pct or 0.0),
            "avg_dist_any_shelter_km": float(r.avg_dist_any_shelter_km or 0.0),
            "avg_dist_wc_confirmed_shelter_km": float(
                r.avg_dist_wc_confirmed_shelter_km or 0.0
            ),
            "avg_pct_nearby_shelters_unrecorded": float(
                r.avg_pct_nearby_shelters_unrecorded or 0.0
            ),
        }
        for r in rows
    ]

    # Optional check against equity_audit_svi_theme3 if present in dataset
    theme3_summary = None
    try:
        t3_sql = f"""
        SELECT
          COUNT(*) AS tracts_joined,
          ROUND(AVG(IF(v.households_no_vehicle >= 150, t3.pct_minority_pop, NULL)), 1) AS avg_minority_pct_in_top_carless_tracts,
          ROUND(AVG(t3.pct_minority_pop), 1) AS county_avg_minority_pct
        FROM {t_vtracts} v
        JOIN {t_theme3} t3 USING (geo_id)
        WHERE v.county_fips = @county_fips
        """
        t3_row = list(bq.query(t3_sql, job_config=job_config).result())[0]
        theme3_summary = {
            "tracts_evaluated": int(t3_row.tracts_joined or 0),
            "avg_minority_pct_in_high_carless_tracts": float(
                t3_row.avg_minority_pct_in_top_carless_tracts or 0.0
            ),
            "county_avg_minority_pct": float(t3_row.county_avg_minority_pct or 0.0),
        }
    except Exception:
        theme3_summary = None

    return {
        "status": "ok",
        "county_fips": county_fips,
        "audit_methodology": (
            "Post-hoc equity and clerical-bias audit. Demographic variables (SVI socioeconomic status, "
            "limited English proficiency, and SVI Theme 3 minority status) are NEVER used as inputs "
            "to exclude or deprioritize tracts; they are audited post-hoc to verify that physical need "
            "(no-vehicle households, disability prevalence, and unrecorded shelter paperwork) receives "
            "equitable emergency resources."
        ),
        "tiers_comparison": tiers,
        "svi_theme3_post_hoc_check": theme3_summary,
        "key_equity_finding": (
            "Across Lee County, the distance penalty between 'any non-surge shelter' (~2-3 km) and a "
            "'confirmed wheelchair-accessible shelter' (~11-16 km) is driven by the 93% UNRECORDED "
            "clerical gap in FEMA's registry. Treating UNRECORDED as 'NO' would falsely classify "
            "high-vulnerability tracts as having zero accessible shelters within 10 km; prioritizing "
            "physical August field inspections in high-need tracts resolves the paperwork blind spot."
        ),
    }


def record_field_assessment(
    shelter_id: int,
    shelter_name: str,
    county_name: str = "Lee",
    fema_wheelchair_status: str = "UNRECORDED",
    assessed_wheelchair_status: str = "FIELD_VERIFIED_YES",
    operational_status: str = "OPEN",
    google_maps_place_id: str = "",
    inspector_notes: str = "",
) -> Dict[str, Any]:
    """Record a physical field inspection or shelter operator update into BigQuery (`shelter_assessments`).

    Implements the README's recommended write-back loop ('The add-on we'd build if we had another
    four hours'): allows a shelter operator or county emergency manager to update an UNRECORDED
    shelter flag after physical inspection while strictly obeying Google Maps Terms of Service
    (storing only `google_maps_place_id`, never caching raw Google Maps text/descriptions).

    Args:
        shelter_id: Unique FEMA shelter_id integer.
        shelter_name: Name of the shelter facility.
        county_name: County name (defaults to 'Lee').
        fema_wheelchair_status: Original 2022 FEMA status ('YES', 'NO', or 'UNRECORDED').
        assessed_wheelchair_status: New field-verified status ('FIELD_VERIFIED_YES' or 'FIELD_VERIFIED_NO').
        operational_status: Physical building status ('OPEN', 'RENAMED_OPEN', 'CLOSED').
        google_maps_place_id: Optional Google Maps `place_id` pointer (permitted under Maps ToS).
        inspector_notes: Brief field inspection note (e.g. 'Verified ADA ramp and backup generator transfer switch').

    Returns:
        Confirmation dictionary with the inserted assessment_id and timestamp.
    """
    bq = get_bq_client()
    table_id = f"{PROJECT_ID}.{DATASET}.shelter_assessments"

    create_sql = f"""
    CREATE TABLE IF NOT EXISTS `{table_id}` (
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
    )
    """
    bq.query(create_sql).result()

    assessment_id = f"asmt-{uuid.uuid4().hex[:10]}"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    insert_sql = f"""
    INSERT INTO `{table_id}` (
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
      assessed_at
    ) VALUES (
      @assessment_id,
      @shelter_id,
      @shelter_name,
      @county_name,
      @fema_wheelchair_status,
      @assessed_wheelchair_status,
      @operational_status,
      @google_maps_place_id,
      NULL,
      'COUNTY_EMERGENCY_MANAGER_FIELD_AUDIT',
      @inspector_notes,
      CURRENT_TIMESTAMP()
    )
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("assessment_id", "STRING", assessment_id),
            bigquery.ScalarQueryParameter("shelter_id", "INT64", int(shelter_id)),
            bigquery.ScalarQueryParameter("shelter_name", "STRING", shelter_name),
            bigquery.ScalarQueryParameter("county_name", "STRING", county_name),
            bigquery.ScalarQueryParameter(
                "fema_wheelchair_status", "STRING", fema_wheelchair_status
            ),
            bigquery.ScalarQueryParameter(
                "assessed_wheelchair_status", "STRING", assessed_wheelchair_status
            ),
            bigquery.ScalarQueryParameter(
                "operational_status", "STRING", operational_status
            ),
            bigquery.ScalarQueryParameter(
                "google_maps_place_id", "STRING", google_maps_place_id or ""
            ),
            bigquery.ScalarQueryParameter(
                "inspector_notes", "STRING", inspector_notes or ""
            ),
        ]
    )
    bq.query(insert_sql, job_config=job_config).result()

    return {
        "status": "ok",
        "assessment_id": assessment_id,
        "shelter_id": int(shelter_id),
        "shelter_name": shelter_name,
        "previous_fema_status": fema_wheelchair_status,
        "new_assessed_status": assessed_wheelchair_status,
        "operational_status": operational_status,
        "google_maps_place_id_stored": google_maps_place_id or None,
        "maps_tos_compliance": "Only place_id pointer stored; no Google Maps content cached.",
        "assessed_at": now_iso,
    }


def classify_persona_and_intent(question: str) -> Dict[str, Any]:
    """Identify the active user persona (LOCAL_PLANNER vs HOSPITAL) and intent topic from a voice/text prompt.

    Args:
        question: The spoken or typed prompt from the user.

    Returns:
        Dictionary with `persona` ('LOCAL_PLANNER' or 'HOSPITAL'), `persona_title`,
        `intent_topic`, `intent_label`, `primary_view`, `confidence`, and `matched_signals`.
    """
    q = (question or "").strip().lower()

    hospital_keywords = {
        "hospital": "Hospital operations",
        "nursing home": "CMS Nursing Homes",
        "nursing": "Nursing facility care",
        "care facility": "Care facilities",
        "care facilities": "Care facilities",
        "patient": "Patient evacuation & transfer",
        "patients": "Patient evacuation & transfer",
        "clinical": "Clinical care continuity",
        "medical": "Medical needs & power",
        "generator": "Backup generator power",
        "generators": "Backup generator power",
        "power": "Electricity-dependent care",
        "electricity": "Electricity-dependent DME",
        "dme": "Durable Medical Equipment (DME)",
        "empower": "HHS emPOWER registry",
        "oxygen": "Oxygen-dependent patients",
        "o2": "Oxygen-dependent patients",
        "dialysis": "ESRD / Dialysis patients",
        "esrd": "ESRD / Dialysis patients",
        "ventilator": "Ventilator-dependent patients",
        "hospice": "At-home hospice patients",
        "beds": "Certified nursing beds",
        "bed": "Certified nursing beds",
        "ambulance": "EMS / Ambulance transfer",
        "mutual aid": "Clinical mutual-aid transfer",
        "mutual-aid": "Clinical mutual-aid transfer",
        "lehigh acres": "Lehigh Acres Health & Rehab",
        "page rehab": "Page Rehabilitation & Healthcare",
        "winkler court": "Winkler Court Nursing Facility",
        "calusa": "Calusa Harbour Care Facility",
        "estero recreation": "Estero Medical Shelter",
        "cms": "CMS certified facilities",
        "doctor": "Clinical staff",
        "nurse": "Nursing staff",
        "icu": "Critical care / ICU",
    }

    planner_keywords = {
        "planner": "County Emergency Planner",
        "emergency manager": "County Emergency Manager",
        "eoc": "Emergency Operations Center",
        "bus": "Municipal transit bus staging",
        "buses": "Municipal transit bus staging",
        "leetran": "LeeTran bus staging",
        "transit": "Zero-Car Transit Lifeline",
        "carless": "No-vehicle households",
        "no vehicle": "No-vehicle households",
        "no-vehicle": "No-vehicle households",
        "vehicle": "Household vehicle access",
        "walkability": "2.0 km Walkability Wall",
        "walk": "Pedestrian evacuation distance",
        "tract": "Census tract vulnerability",
        "tracts": "Census tract vulnerability",
        "12071001401": "Census Tract 12071001401",
        "12071001915": "Census Tract 12071001915",
        "shelter": "FEMA Shelter Registry",
        "shelters": "FEMA Shelter Registry",
        "ghost shelter": "Ghost Shelter Audit",
        "wheelchair": "Wheelchair accessibility",
        "ada": "ADA / Wheelchair verification",
        "accessible": "Shelter accessibility",
        "accessibility": "Shelter accessibility",
        "surge": "SLOSH storm-surge exposure",
        "slosh": "SLOSH storm-surge zone",
        "flood": "100-year floodplain exposure",
        "dunbar": "Dunbar High School (Surge Zone)",
        "harns marsh": "Harns Marsh Middle (Surge Zone)",
        "north fort myers": "North Fort Myers Academy",
        "veterans park": "Veterans Park Academy",
        "alico": "Alico Arena",
        "inspect": "August field inspection triage",
        "inspection": "August field inspection triage",
        "audit": "County readiness audit",
        "equity": "Post-hoc SVI equity audit",
        "svi": "Social Vulnerability Index",
        "poverty": "Socioeconomic vulnerability",
        "unrecorded": "Unrecorded FEMA paperwork gap",
    }

    hosp_matches: List[str] = []
    plan_matches: List[str] = []

    for kw, label in hospital_keywords.items():
        if kw in q and label not in hosp_matches:
            hosp_matches.append(label)

    for kw, label in planner_keywords.items():
        if kw in q and label not in plan_matches:
            plan_matches.append(label)

    # Strong explicit persona overrides
    if any(w in q for w in ["as a hospital", "hospital persona", "nursing home", "care facility", "patient", "dialysis", "oxygen", "ventilator", "dme", "empower", "mutual aid", "certified beds", "lehigh acres", "page rehab"]):
        hosp_score = len(hosp_matches) + 3
    else:
        hosp_score = len(hosp_matches)

    if any(w in q for w in ["as a planner", "local planner", "emergency manager", "carless", "no-vehicle", "no vehicle", "bus", "buses", "walkability", "census tract", "ghost shelter", "wheelchair", "surge", "equity", "dunbar", "harns marsh"]):
        plan_score = len(plan_matches) + 3
    else:
        plan_score = len(plan_matches)

    if hosp_score > plan_score:
        persona = "HOSPITAL"
        persona_title = "🏥 Hospital & Care Facility Operations"
        persona_subtitle = "Acute Care · CMS Nursing Homes · HHS emPOWER DME · Backup Power & Patient Transfer"
        matched_signals = hosp_matches or ["Clinical / Medical Power & Transfer Readiness"]
        confidence = min(0.99, round(0.82 + 0.04 * hosp_score, 2))

        if any(w in q for w in ["oxygen", "o2", "dialysis", "esrd", "dme", "empower", "ventilator", "hospice", "home health", "electricity"]):
            intent_topic = "DME_OXYGEN_DIALYSIS"
            intent_label = "Electricity-Dependent DME, Oxygen & Dialysis Surge Triage"
        elif any(w in q for w in ["route", "transfer", "ambulance", "evacuate", "estero", "special medical", "rename", "open", "closed", "lehigh"]):
            intent_topic = "MEDICAL_SHELTER_ROUTING"
            intent_label = "Patient Transfer Routing & Live Facility Verification"
        else:
            intent_topic = "NURSING_HOME_GENERATOR"
            intent_label = "Generator-Blind Nursing Home Alert & Mutual-Aid Triage"
        primary_view = "medical"
    else:
        persona = "LOCAL_PLANNER"
        persona_title = "🏛️ Local Emergency Planner (County EOC)"
        persona_subtitle = "Shelter Triage · Zero-Car Bus Staging · Storm Surge De-Designation · Equity Audit"
        matched_signals = plan_matches or ["County Shelter & Evacuation Transit Planning"]
        confidence = min(0.99, round(0.84 + 0.03 * max(plan_score, 1), 2))

        if any(w in q for w in ["carless", "no-vehicle", "no vehicle", "bus", "buses", "transit", "walkability", "walk", "12071001401", "12071001915", "pickup", "staging"]):
            intent_topic = "TRANSIT_LIFELINE"
            intent_label = "Zero-Car Transit Lifeline & T-Minus 48h Bus Staging"
            primary_view = "transit"
        elif any(w in q for w in ["equity", "svi", "poverty", "minority", "fairness", "bias", "demographic"]):
            intent_topic = "EQUITY_PAPERWORK"
            intent_label = "Post-Hoc Demographic & Paperwork Bias Audit"
            primary_view = "equity"
        elif any(w in q for w in ["surge", "slosh", "flood", "dunbar", "harns marsh"]):
            intent_topic = "SURGE_EXPOSURE"
            intent_label = "Storm Surge SLOSH De-Designation & Safe Shelter Audit"
            primary_view = "shelters"
        else:
            intent_topic = "SHELTER_AUDIT"
            intent_label = "August Ghost Shelter & Accessibility Inspection Triage"
            primary_view = "shelters"

    return {
        "persona": persona,
        "persona_title": persona_title,
        "persona_subtitle": persona_subtitle,
        "intent_topic": intent_topic,
        "intent_label": intent_label,
        "primary_view": primary_view,
        "confidence": confidence,
        "matched_signals": matched_signals[:5],
    }


def build_map_overlay_pins(
    resolved: Dict[str, Any],
    shelter_audit: Dict[str, Any],
    transit_gaps: Dict[str, Any],
    medical_gaps: Dict[str, Any],
    persona: str = "LOCAL_PLANNER",
) -> Dict[str, Any]:
    """Build interactive map overlay pins and evacuation/transfer route corridors for any county."""
    active_fips = resolved.get("county_fips", DEFAULT_COUNTY_FIPS)
    raw_cname = (resolved.get("county_name") or shelter_audit.get("county_name") or "Lee").strip()
    if raw_cname.lower().endswith("county"):
        raw_cname = raw_cname[:-6].strip()
    state_code = (resolved.get("state") or "FL").strip()

    pins: List[Dict[str, Any]] = []
    seen_shelter_ids: set[int] = set()

    # 1. Surge-exposed shelters (up to 4)
    for s in (shelter_audit.get("surge_or_flood_exposed_shelters") or [])[:4]:
        lat = s.get("latitude")
        lon = s.get("longitude")
        if lat is None or lon is None:
            continue
        sid = int(s.get("shelter_id") or 0)
        seen_shelter_ids.add(sid)
        cap = int(s.get("effective_capacity") or 0)
        fema_rec = s.get("fema_2022_record") or {}
        pins.append(
            {
                "id": f"surge-{sid}",
                "shelter_id": sid,
                "category": "surge_danger",
                "color": "#ef4444",
                "icon": "🌊",
                "badge": "Flood / Storm Surge Danger Zone",
                "name": s.get("shelter_name") or "Surge-Exposed Shelter",
                "title": s.get("shelter_name") or "Surge-Exposed Shelter",
                "address": s.get("address_1") or "",
                "city": s.get("city") or "",
                "state": s.get("state") or state_code,
                "lat": float(lat),
                "lon": float(lon),
                "capacity": cap,
                "metric_cap": f"{cap:,} Spaces (Do Not Use for Storm Surge)",
                "metric_status": "Storm Surge / Flood Zone",
                "fema_wheelchair": fema_rec.get("wheelchair_accessible", "UNRECORDED"),
                "fema_generator": fema_rec.get("generator_onsite", "UNRECORDED"),
                "summary": (
                    f"Located in a storm-surge or flood danger zone ({s.get('address_1') or ''}, {s.get('city') or ''}). "
                    f"Capacity {cap:,}. Do not route coastal surge evacuees here before landfall."
                ),
                "route_to": None,
            }
        )

    # 2. Confirmed generator / wheelchair / medical shelters (up to 4)
    verified_list = shelter_audit.get("verified_safe_or_power_shelters") or [
        x
        for x in (shelter_audit.get("top_candidate_shelters") or [])
        if (
            (x.get("fema_2022_record") or {}).get("generator_onsite") == "YES"
            or (x.get("fema_2022_record") or {}).get("wheelchair_accessible") == "YES"
            or x.get("is_medical") is True
        )
        and (x.get("fema_2022_record") or {}).get("in_surge_slosh_area") != "YES"
    ]
    for s in verified_list[:4]:
        lat = s.get("latitude")
        lon = s.get("longitude")
        sid = int(s.get("shelter_id") or 0)
        if lat is None or lon is None or sid in seen_shelter_ids:
            continue
        seen_shelter_ids.add(sid)
        cap = int(s.get("effective_capacity") or 0)
        fema_rec = s.get("fema_2022_record") or {}
        gen_st = fema_rec.get("generator_onsite", "UNRECORDED")
        wc_st = s.get("effective_wheelchair_status") or fema_rec.get("wheelchair_accessible", "UNRECORDED")
        pins.append(
            {
                "id": f"verified-{sid}",
                "shelter_id": sid,
                "category": "shelter_verified",
                "color": "#10b981",
                "icon": "🟢",
                "badge": "Verified Safe / Power Shelter",
                "name": s.get("shelter_name") or "Verified Safe Shelter",
                "title": s.get("shelter_name") or "Verified Safe Shelter",
                "address": s.get("address_1") or "",
                "city": s.get("city") or "",
                "state": s.get("state") or state_code,
                "lat": float(lat),
                "lon": float(lon),
                "capacity": cap,
                "metric_cap": f"{cap:,} Safe Spaces",
                "metric_status": f"Generator: {gen_st} · Wheelchair: {wc_st}",
                "fema_wheelchair": wc_st,
                "fema_generator": gen_st,
                "summary": (
                    f"Confirmed safe shelter outside storm surge ({s.get('address_1') or ''}, {s.get('city') or ''}). "
                    f"Capacity {cap:,} evacuees · Backup Power: {gen_st} · Wheelchair Access: {wc_st}."
                ),
                "route_to": None,
            }
        )

    # 3. Top inspection shelters (UNRECORDED ADA/gen) (up to 5)
    unverified_candidates = (
        (shelter_audit.get("august_field_inspection_top3") or [])
        + (shelter_audit.get("top_candidate_shelters") or [])
    )
    unverified_added = 0
    for s in unverified_candidates:
        if unverified_added >= 5:
            break
        lat = s.get("latitude")
        lon = s.get("longitude")
        sid = int(s.get("shelter_id") or 0)
        if lat is None or lon is None or sid in seen_shelter_ids:
            continue
        seen_shelter_ids.add(sid)
        unverified_added += 1
        cap = int(s.get("effective_capacity") or 0)
        fema_rec = s.get("fema_2022_record") or {}
        gen_st = fema_rec.get("generator_onsite", "UNRECORDED")
        wc_st = fema_rec.get("wheelchair_accessible", "UNRECORDED")
        pins.append(
            {
                "id": f"unverified-{sid}",
                "shelter_id": sid,
                "category": "shelter_unverified",
                "color": "#f59e0b",
                "icon": "🟡",
                "badge": "Shelter Needs Safety Check",
                "name": s.get("shelter_name") or "Unverified Shelter",
                "title": s.get("shelter_name") or "Unverified Shelter",
                "address": s.get("address_1") or "",
                "city": s.get("city") or "",
                "state": s.get("state") or state_code,
                "lat": float(lat),
                "lon": float(lon),
                "capacity": cap,
                "metric_cap": f"{cap:,} Spaces",
                "metric_status": f"Wheelchair: {wc_st} · Generator: {gen_st}",
                "fema_wheelchair": wc_st,
                "fema_generator": gen_st,
                "summary": (
                    f"High-capacity shelter ({cap:,} spaces) at {s.get('address_1') or ''}, {s.get('city') or ''}. "
                    f"Wheelchair access ({wc_st}) or generator power ({gen_st}) is unrecorded in federal files—send a team to check before storm season."
                ),
                "route_to": None,
            }
        )

    # 4. Priority Zero-Car Bus Pickup Tracts (up to 4)
    for t in (transit_gaps.get("priority_zero_car_tracts") or [])[:4]:
        coords = t.get("pickup_staging_coordinates") or {}
        t_lat = coords.get("lat")
        t_lon = coords.get("lon")
        if t_lat is None or t_lon is None:
            continue
        hh_no_veh = int(t.get("households_no_vehicle") or 0)
        buses = int(coords.get("recommended_municipal_buses") or 2)
        geo_id = str(t.get("geo_id") or "")
        ns = t.get("nearest_non_surge_shelter") or {}
        route_to = None
        if ns and ns.get("latitude") is not None and ns.get("longitude") is not None:
            route_to = {
                "lat": float(ns["latitude"]),
                "lon": float(ns["longitude"]),
                "name": ns.get("shelter_name") or "Nearest Safe Shelter",
                "address": ns.get("address_1") or "",
                "city": ns.get("city") or "",
                "state": ns.get("state") or state_code,
                "distance_km": float(ns.get("straight_line_distance_km") or 0.0),
            }
        pins.append(
            {
                "id": f"bus-{geo_id}",
                "category": "bus_pickup",
                "color": "#06b6d4",
                "icon": "🚌",
                "badge": "Bus Pickup Zone (No-Car Families)",
                "name": f"Neighborhood Pickup Zone (Tract {geo_id[-6:] or geo_id})",
                "title": f"Bus Pickup Zone · Tract {geo_id} ({hh_no_veh:,} No-Car Homes)",
                "address": f"GPS Pickup Point ({t_lat}, {t_lon})",
                "city": raw_cname,
                "state": state_code,
                "lat": float(t_lat),
                "lon": float(t_lon),
                "capacity": hh_no_veh,
                "metric_cap": f"{hh_no_veh:,} Homes Without Cars",
                "metric_status": f"Stage {buses} Evacuation Buses (48h Early)",
                "summary": (
                    f"{hh_no_veh:,} households ({t.get('pct_no_vehicle', 0)}% of neighborhood) have no car. "
                    f"Stage {buses} transit buses here 48 hours before landfall"
                    + (
                        f" to shuttle families {route_to['distance_km']} km to {route_to['name']}."
                        if route_to
                        else "."
                    )
                ),
                "route_to": route_to,
            }
        )

    # 5. Top CMS Nursing Homes (up to 4)
    for nh in (medical_gaps.get("top_nursing_homes") or [])[:4]:
        nh_lat = nh.get("latitude")
        nh_lon = nh.get("longitude")
        if nh_lat is None or nh_lon is None:
            continue
        beds = int(nh.get("certified_beds") or 0)
        ccn = str(nh.get("cms_ccn") or nh.get("provider_name") or "")
        gen_s = nh.get("nearest_generator_confirmed_shelter") or nh.get("nearest_any_non_surge_shelter") or {}
        route_to = None
        if gen_s and gen_s.get("latitude") is not None and gen_s.get("longitude") is not None:
            route_to = {
                "lat": float(gen_s["latitude"]),
                "lon": float(gen_s["longitude"]),
                "name": gen_s.get("shelter_name") or "Backup Power Shelter",
                "address": gen_s.get("address_1") or "",
                "city": gen_s.get("city") or "",
                "state": state_code,
                "distance_km": float(gen_s.get("straight_line_distance_km") or 0.0),
            }
        pins.append(
            {
                "id": f"nh-{ccn}",
                "category": "nursing_home",
                "color": "#f43f5e",
                "icon": "🏥",
                "badge": "Nursing Home / Care Center",
                "name": nh.get("provider_name") or "Nursing Care Center",
                "title": f"{nh.get('provider_name') or 'Nursing Center'} ({beds} Beds)",
                "address": nh.get("provider_address") or "",
                "city": nh.get("city") or "",
                "state": nh.get("state") or state_code,
                "lat": float(nh_lat),
                "lon": float(nh_lon),
                "capacity": beds,
                "metric_cap": f"{beds:,} Nursing Beds",
                "metric_status": (
                    f"{route_to['distance_km']} km to {route_to['name']}"
                    if route_to
                    else "Needs Backup Power Transfer Plan"
                ),
                "summary": (
                    f"Licensed care center with {beds:,} nursing beds at {nh.get('provider_address') or ''}, {nh.get('city') or ''}. "
                    + (
                        f"Closest backup-power shelter is {route_to['name']} ({route_to['distance_km']} km away)."
                        if route_to
                        else "Verify backup generator and ambulance transfer plan."
                    )
                ),
                "route_to": route_to,
            }
        )

    center_lat = resolved.get("center_lat")
    center_lon = resolved.get("center_lon")
    if (center_lat is None or center_lon is None) and pins:
        center_lat = round(sum(p["lat"] for p in pins) / len(pins), 5)
        center_lon = round(sum(p["lon"] for p in pins) / len(pins), 5)

    return {
        "county_fips": active_fips,
        "county_name": raw_cname,
        "state": state_code,
        "center_lat": float(center_lat or 26.5965),
        "center_lon": float(center_lon or -81.8414),
        "zoom": 11,
        "pins": pins[:20],
    }


def build_persona_action_response(
    question: str,
    county_fips: str = DEFAULT_COUNTY_FIPS,
) -> Dict[str, Any]:
    """Build dynamic, county-aware persona action data, KPIs, action cards, map overlays, and spoken feedback.

    Args:
        question: User's voice or text question.
        county_fips: Fallback 5-character county FIPS code (defaults to '12071' for Lee County, FL).

    Returns:
        Structured dictionary with `active_county`, `persona_info`, `voice_summary`, `persona_kpis`,
        `action_cards`, `map_overlays`, and `question_matched_records`.
    """
    resolved = resolve_county_from_query(
        question, fallback_fips=county_fips or DEFAULT_COUNTY_FIPS
    )
    active_fips = resolved["county_fips"]
    raw_cname = (resolved.get("county_name") or "Lee").strip()
    state_code = (resolved.get("state") or "FL").strip()
    if raw_cname.lower().endswith("county"):
        county_short = raw_cname[:-6].strip()
        county_label = f"{raw_cname}, {state_code}"
    else:
        county_short = raw_cname
        county_label = f"{raw_cname} County, {state_code}"

    p_info = classify_persona_and_intent(question)
    persona = p_info["persona"]
    intent = p_info["intent_topic"]
    p_info["active_county_fips"] = active_fips
    p_info["active_county_name"] = county_short
    p_info["active_county_label"] = county_label
    p_info["intent_label"] = f"{county_label} — {p_info['intent_label']}"
    q_lower = (question or "").lower()

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_sh = pool.submit(audit_county_shelters, active_fips, 12)
        f_tr = pool.submit(find_zero_car_transit_gaps, active_fips, 5)
        f_md = pool.submit(check_medical_power_gaps, active_fips, 8)
        f_eq = pool.submit(run_equity_audit, active_fips)
        shelter_audit = f_sh.result()
        transit_gaps = f_tr.result()
        medical_gaps = f_md.result()
        equity_audit = f_eq.result()

    ep = shelter_audit.get("epistemic_summary", {})
    wc_info = ep.get("wheelchair_accessible", {})
    gen_info = ep.get("generator_onsite", {})
    emp = medical_gaps.get("empower_county_level_metrics", {})
    cms_sum = medical_gaps.get("cms_nursing_home_summary", {})

    top3_inspect = shelter_audit.get("august_field_inspection_top3", [])
    top_cands = shelter_audit.get("top_candidate_shelters", [])
    b1 = top3_inspect[0] if top3_inspect else (top_cands[0] if top_cands else {})
    verified_list = shelter_audit.get("verified_safe_or_power_shelters", [])
    v1 = verified_list[0] if verified_list else b1

    if persona == "HOSPITAL":
        top_nhs = medical_gaps.get("top_nursing_homes", [])
        top_nh = top_nhs[0] if top_nhs else {}
        second_nh = next(
            (n for n in top_nhs if "LEHIGH" in n.get("provider_name", "").upper()),
            top_nhs[1] if len(top_nhs) > 1 else top_nh,
        )

        matched_nhs = [
            n
            for n in top_nhs
            if any(
                tok in q_lower
                for tok in n.get("provider_name", "").lower().split()
                if len(tok) > 4
                and tok not in {"health", "healthcare", "rehabilitation", "center", "nursing", "facility", "manor"}
            )
        ]

        nh1_gen = (
            top_nh.get("nearest_generator_confirmed_shelter")
            or top_nh.get("nearest_any_non_surge_shelter")
            or {}
        )
        nh2_gen = (
            second_nh.get("nearest_generator_confirmed_shelter")
            or second_nh.get("nearest_any_non_surge_shelter")
            or {}
        )

        nh_count = int(cms_sum.get("total_nursing_homes_in_county", 0))
        nh_beds = int(cms_sum.get("total_certified_nursing_home_beds", 0))
        dme_total = int(emp.get("power_dependent_raw_value", 0))
        o2_total = int(emp.get("oxygen_services_dme", 0))
        dialysis_total = int(emp.get("dialysis_esrd_dme", 0))
        gen_yes = int(gen_info.get("YES", 0))
        gen_unrec = int(gen_info.get("UNRECORDED", 0))
        total_sh = int(ep.get("total_shelters", 0))
        med_sh_cnt = int(ep.get("medical_designated_shelters", 0))

        top_nh_name = top_nh.get("provider_name", f"Top {county_short} Care Center")
        top_nh_beds = int(top_nh.get("certified_beds", 0))
        top_nh_city = top_nh.get("city", county_short)
        target_gen_name = nh1_gen.get("shelter_name") or v1.get("shelter_name") or b1.get("shelter_name") or "Nearest Safe Shelter"
        target_gen_dist = nh1_gen.get("straight_line_distance_km", 0.0)

        if intent == "DME_OXYGEN_DIALYSIS":
            voice_summary = (
                f"In {county_label}, {dme_total:,} Medicare patients depend on plug-in medical equipment at home, "
                f"including {o2_total:,} on oxygen and {dialysis_total:,} on dialysis. "
                f"Right now, only {gen_yes} of {total_sh} county shelters have confirmed backup generators on file, while {gen_unrec} shelters are unverified. "
                f"We recommend locking in backup power at {target_gen_name} and inspecting generator switches at {b1.get('shelter_name', 'the largest county shelter')} in {b1.get('city', county_short)} before storm season."
            )
        elif intent == "MEDICAL_SHELTER_ROUTING":
            voice_summary = (
                f"Across {county_label}, {nh_count} nursing homes with {nh_beds:,} beds share only {gen_yes} confirmed generator shelters. "
                f"For {top_nh_name} ({top_nh_beds} beds in {top_nh_city}), the closest backup-power shelter is {target_gen_name}, located {target_gen_dist} kilometers away. "
                f"Verify ambulance transfer routes and confirm current building status at {second_nh.get('provider_name', top_nh_name)} at least 48 hours before landfall."
            )
        else:
            voice_summary = (
                f"In {county_label}, {nh_count} nursing homes caring for {nh_beds:,} residents and {dme_total:,} home medical-power patients "
                f"face a major backup power gap, with {gen_unrec} of {total_sh} shelters missing generator records. "
                f"Priority one is pairing {top_nh_name} ({top_nh_beds} beds) with {target_gen_name} ({target_gen_dist} kilometers away) and verifying backup generators at {b1.get('shelter_name', 'top shelters')}."
            )

        persona_kpis = [
            {
                "label": "Nursing Home Beds at Risk",
                "value": f"{nh_beds:,}",
                "sub": f"Across {nh_count} licensed {county_short} County care centers",
                "color": "#f87171",
            },
            {
                "label": "Home Medical Power Patients",
                "value": f"{dme_total:,}",
                "sub": f"{o2_total:,} Oxygen · {dialysis_total:,} Dialysis in {county_short} County",
                "color": "#fbbf24",
            },
            {
                "label": "Confirmed Generator Shelters",
                "value": f"{gen_yes} of {total_sh}",
                "sub": f"{gen_unrec} shelters ({gen_info.get('pct_unrecorded', 0)}%) need generator check",
                "color": "#d8b4fe",
            },
            {
                "label": "Medical & Power Shelters",
                "value": f"{max(med_sh_cnt, gen_yes)}",
                "sub": f"Top: {v1.get('shelter_name', 'County Medical Shelter')} ({v1.get('city', county_short)})",
                "color": "#38bdf8",
            },
        ]

        action_cards = [
            {
                "badge": f"STEP 1 · {county_short.upper()} AMBULANCE TRANSFER PLAN",
                "badge_class": "no",
                "title": f"Pair {top_nh_name} ({top_nh_beds} Beds) with {target_gen_name}",
                "detail": (
                    f"Within 10 km of {top_nh_name} in {top_nh_city}, {top_nh.get('surrounding_10km_shelters', {}).get('generator_unrecorded', 0)} shelters have unverified backup power and "
                    f"{top_nh.get('surrounding_10km_shelters', {}).get('generator_confirmed_yes', 0)} have confirmed generators. "
                    f"Closest backup-power shelter is {target_gen_name} ({target_gen_dist} km)."
                ),
                "action_type": "verify_route",
                "action_label": "🚑 Check Ambulance Route on Google Maps",
                "place_name": target_gen_name,
                "address": nh1_gen.get("address_1") or v1.get("address_1") or b1.get("address_1") or "",
                "city": nh1_gen.get("city") or v1.get("city") or b1.get("city") or top_nh_city,
                "state": state_code,
                "origin_lat": top_nh.get("latitude"),
                "origin_lon": top_nh.get("longitude"),
                "origin_label": f"{top_nh_name} ({top_nh_beds} beds)",
            },
            {
                "badge": "STEP 2 · LIVE CARE FACILITY NAME & STATUS CHECK",
                "badge_class": "renamed",
                "title": f"Verify Current Status: {second_nh.get('provider_name', top_nh_name)} ({second_nh.get('certified_beds', top_nh_beds)} Beds)",
                "detail": (
                    f"2022 federal records list '{second_nh.get('provider_name', top_nh_name)}' at "
                    f"{second_nh.get('provider_address', '')}, {second_nh.get('city', top_nh_city)}. "
                    f"Verify live operating name and dispatch contact on Google Maps; nearest generator shelter is {nh2_gen.get('straight_line_distance_km', target_gen_dist)} km away."
                ),
                "action_type": "verify_place",
                "action_label": "🗺️ Check Care Center Live on Google Maps",
                "place_name": second_nh.get("provider_name", top_nh_name),
                "address": second_nh.get("provider_address", ""),
                "city": second_nh.get("city", top_nh_city),
                "state": state_code,
            },
            {
                "badge": "STEP 3 · BACKUP GENERATOR INSPECTION",
                "badge_class": "unrec",
                "title": f"Confirm Generator Power at {b1.get('shelter_name', 'Top County Shelter')} (Cap {b1.get('effective_capacity', 0):,})",
                "detail": (
                    f"{county_label} has {o2_total:,} oxygen and {dialysis_total:,} dialysis patients living at home. "
                    f"Inspect and confirm backup generator power at {b1.get('shelter_name', 'this high-capacity shelter')} ({b1.get('address_1', '')}, {b1.get('city', county_short)}) to keep hospital ERs from overflowing."
                ),
                "action_type": "field_audit",
                "action_label": f"⚡ Mark Generator & Access Verified (ID {b1.get('shelter_id', 0)})",
                "shelter_id": b1.get("shelter_id", 0),
                "shelter_name": b1.get("shelter_name", "Top County Shelter"),
                "county_name": county_short,
                "prev_status": "UNRECORDED",
            },
        ]

        matched_records = matched_nhs if matched_nhs else top_nhs[:4]

    else:
        # LOCAL_PLANNER Persona
        top_tracts = transit_gaps.get("priority_zero_car_tracts", [])
        t1 = top_tracts[0] if top_tracts else {}
        t2 = top_tracts[1] if len(top_tracts) > 1 else t1
        surge_list = shelter_audit.get("surge_or_flood_exposed_shelters", [])
        s1 = surge_list[0] if surge_list else (top3_inspect[1] if len(top3_inspect) > 1 else b1)

        total_sh = int(ep.get("total_shelters", 0))
        evac_cap = int(ep.get("total_plausible_evac_capacity", 0))
        wc_unrec = int(wc_info.get("UNRECORDED", 0))
        wc_pct_unrec = wc_info.get("pct_unrecorded", 0.0)
        surge_yes_cnt = int(ep.get("in_surge_slosh_area", {}).get("YES", 0))
        flood_yes_cnt = int(ep.get("in_100_yr_floodplain", {}).get("YES", 0))
        danger_cnt = len(surge_list)
        carless_top5 = int(transit_gaps.get("total_carless_households_in_top_tracts", 0))

        t1_coords = t1.get("pickup_staging_coordinates", {})
        t1_ns = t1.get("nearest_non_surge_shelter") or b1 or {}
        t1_hh = int(t1.get("households_no_vehicle", 0))
        t1_buses = int(t1_coords.get("recommended_municipal_buses", 4))
        t1_dist = (
            t1.get("nearest_confirmed_wheelchair_shelter", {}) or {}
        ).get("straight_line_distance_km") or t1_ns.get("straight_line_distance_km", 0.0)
        t2_dist = (t2.get("nearest_non_surge_shelter") or {}).get("straight_line_distance_km", 0.0)

        b1_name = b1.get("shelter_name", f"Top {county_short} Shelter")
        b1_cap = int(b1.get("effective_capacity", 0))
        b1_city = b1.get("city", county_short)
        b1_addr = b1.get("address_1", "")
        s1_name = s1.get("shelter_name", b1_name)
        s1_city = s1.get("city", b1_city)
        s1_addr = s1.get("address_1", b1_addr)
        s1_cap = int(s1.get("effective_capacity", 0))

        if intent == "TRANSIT_LIFELINE":
            voice_summary = (
                f"In {county_label}, the top five neighborhoods without cars have {carless_top5:,} households that need transit help to evacuate. "
                f"The highest-need neighborhood, Tract {t1.get('geo_id', '')}, has {t1_hh:,} carless homes and sits {t1_dist} kilometers from the closest confirmed wheelchair shelter. "
                f"Stage {t1_buses} transit buses at the pickup point in {t1_ns.get('city', county_short)} 48 hours before landfall to shuttle families safely to {t1_ns.get('shelter_name', b1_name)}."
            )
        elif intent == "SURGE_EXPOSURE":
            if surge_list:
                surge_names = " and ".join(x.get("shelter_name", "") for x in surge_list[:2])
                voice_summary = (
                    f"Out of {total_sh} shelters in {county_label}, {danger_cnt} facilities—including {surge_names}—sit inside a storm-surge or flood danger zone. "
                    f"In addition, {ep.get('in_surge_slosh_area', {}).get('UNRECORDED', 0)} shelters have unverified flood-zone paperwork. "
                    f"Remove {s1_name} in {s1_city} from pre-landfall hurricane evacuation routing and send a team to inspect {b1_name} ({b1_cap:,} spaces) right away."
                )
            else:
                voice_summary = (
                    f"Across {county_label}'s {total_sh} registered shelters, {ep.get('in_surge_slosh_area', {}).get('UNRECORDED', 0)} facilities have unverified storm-surge paperwork on file. "
                    f"Before a storm approaches, verify flood-zone safety and wheelchair access at your largest shelter, {b1_name} ({b1_cap:,} spaces in {b1_city})."
                )
        elif intent == "EQUITY_PAPERWORK":
            voice_summary = (
                f"In {county_label}, low-income and high-need neighborhoods are usually within 3 kilometers of a shelter building, "
                f"but sit much farther from a confirmed wheelchair-accessible shelter because {wc_pct_unrec}% of county shelters ({wc_unrec} of {total_sh}) have blank accessibility paperwork. "
                f"Sending an inspection team to {b1_name} in {b1_city} unlocks {b1_cap:,} verified spaces for vulnerable families."
            )
        else:
            voice_summary = (
                f"{county_label} has {total_sh} shelters with room for {evac_cap:,} evacuees, but {wc_unrec} shelters ({wc_pct_unrec}%) are missing wheelchair accessibility records "
                f"and {carless_top5:,} families in the top five transit zones have no car. "
                f"Start by inspecting {b1_name} ({b1_cap:,} spaces in {b1_city}) and staging {t1_buses} evacuation buses for Tract {t1.get('geo_id', '')} 48 hours before landfall."
            )

        surge_sub = (
            ", ".join(x.get("shelter_name", "") for x in surge_list[:2])
            if surge_list
            else f"{ep.get('in_surge_slosh_area', {}).get('UNRECORDED', 0)} shelters need flood-zone check"
        )

        persona_kpis = [
            {
                "label": f"{county_short} Shelter Capacity",
                "value": f"{evac_cap:,}",
                "sub": f"{ep.get('evac_eligible_shelters', 0)} Evac shelters · {ep.get('post_impact_only_shelters', 0)} Post-storm only",
                "color": "#38bdf8",
            },
            {
                "label": "Missing Wheelchair Info",
                "value": f"{wc_pct_unrec}%",
                "sub": f"{wc_info.get('YES', 0)} Confirmed · {wc_info.get('NO', 0)} No · {wc_unrec} Unchecked",
                "color": "#d8b4fe",
            },
            {
                "label": "Shelters in Flood / Surge Zone",
                "value": f"{danger_cnt} FLAGGED" if danger_cnt > 0 else f"{surge_yes_cnt + flood_yes_cnt} FLAGGED",
                "sub": surge_sub,
                "color": "#f87171",
            },
            {
                "label": "No-Car Homes (Top 5 Zones)",
                "value": f"{carless_top5:,}",
                "sub": f"Need bus pickup in {county_short} County (> 2 km walk)",
                "color": "#4ade80",
            },
        ]

        action_cards = [
            {
                "badge": f"STEP 1 · {county_short.upper()} SHELTER SAFETY CHECK",
                "badge_class": "unrec",
                "title": f"Inspect #1 Unverified Shelter: {b1_name} ({b1_cap:,} Spaces)",
                "detail": (
                    f"Located at {b1_addr}, {b1_city}. "
                    f"Wheelchair ramp access and backup generator status were left blank in federal records. "
                    f"Confirm physical status to unlock {b1_cap:,} safe spaces for {county_short} County residents."
                ),
                "action_type": "field_audit",
                "action_label": "✍️ Mark Shelter Checked (Wheelchair & Power YES)",
                "shelter_id": b1.get("shelter_id", 0),
                "shelter_name": b1_name,
                "address": b1_addr,
                "city": b1_city,
                "county_name": county_short,
                "prev_status": "UNRECORDED",
            },
            {
                "badge": "STEP 2 · 48-HOUR BUS PICKUP PLAN",
                "badge_class": "yes",
                "title": f"Stage {t1_buses} Transit Buses in Tract {t1.get('geo_id', '')} ({t1_hh:,} No-Car Homes)",
                "detail": (
                    f"Pickup GPS: ({t1_coords.get('lat', resolved.get('center_lat'))}, {t1_coords.get('lon', resolved.get('center_lon'))}). "
                    f"{t1.get('pct_no_vehicle', 0)}% of homes have no car and sit {t1_dist} km from a confirmed wheelchair shelter "
                    f"(Tract {t2.get('geo_id', '')} is {t2_dist} km from any safe shelter)."
                ),
                "action_type": "verify_route",
                "action_label": "🚌 Check Bus Route Live on Google Maps",
                "place_name": t1_ns.get("shelter_name", b1_name),
                "address": t1_ns.get("address_1", b1_addr),
                "city": t1_ns.get("city", b1_city),
                "state": state_code,
                "origin_lat": t1_coords.get("lat"),
                "origin_lon": t1_coords.get("lon"),
                "origin_label": f"Tract {t1.get('geo_id', '')} Bus Pickup ({t1_hh:,} no-car homes)",
            },
            {
                "badge": (
                    "STEP 3 · FLOOD & STORM SURGE WARNING"
                    if surge_list
                    else "STEP 3 · LIVE SHELTER BUILDING CHECK"
                ),
                "badge_class": "surge" if surge_list else "unrec",
                "title": (
                    f"Do Not Use for Storm Surge: {s1_name} (Cap {s1_cap:,})"
                    if surge_list
                    else f"Verify Building Status on Google Maps: {s1_name} (Cap {s1_cap:,})"
                ),
                "detail": (
                    f"Located at {s1_addr}, {s1_city}. "
                    + (
                        "Federal records flag this building inside a storm-surge or flood zone. Remove from coastal evacuation routing and check current status on Google Maps."
                        if surge_list
                        else "Verify that this shelter facility is open, operating under its current name, and reachable on Google Maps."
                    )
                ),
                "action_type": "verify_place",
                "action_label": "🗺️ Check Building Live on Google Maps",
                "place_name": s1_name,
                "address": s1_addr,
                "city": s1_city,
                "state": state_code,
            },
        ]

        matched_records = top_tracts if intent == "TRANSIT_LIFELINE" else top3_inspect

    map_overlays = build_map_overlay_pins(
        resolved=resolved,
        shelter_audit=shelter_audit,
        transit_gaps=transit_gaps,
        medical_gaps=medical_gaps,
        persona=persona,
    )

    return {
        "county_fips": active_fips,
        "county_name": county_short,
        "county_label": county_label,
        "active_county": resolved,
        "persona_info": p_info,
        "voice_summary": voice_summary,
        "persona_kpis": persona_kpis,
        "action_cards": action_cards,
        "map_overlays": map_overlays,
        "question_matched_records": matched_records,
        "epistemic_summary": ep,
        "option_1_shelter_audit": shelter_audit,
        "option_2_zero_car_transit_lifeline": transit_gaps,
        "option_3_medical_power_alert": medical_gaps,
        "post_hoc_equity_audit": equity_audit,
    }


def _clean_for_spoken_readback(text: str) -> str:
    """Clean any technical symbols or database tokens from a voice script so it sounds natural."""
    cleaned = (text or "").strip()
    cleaned = re.sub(r"[*_`#]+", "", cleaned)
    cleaned = cleaned.replace("in_surge_slosh_area", "storm surge flood zone")
    cleaned = cleaned.replace("SLOSH", "storm surge")
    cleaned = cleaned.replace("UNRECORDED", "unchecked on paper")
    cleaned = cleaned.replace("NULL", "blank")
    cleaned = cleaned.replace("ST_DISTANCE", "straight-line distance")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def generate_paraphrased_voice_script(
    question: str,
    persona_payload: Dict[str, Any],
) -> str:
    """Paraphrase the county readiness findings for `question` into a natural, specific 3-4 sentence spoken briefing.

    Uses Gemini 2.5 Flash to craft a warm, human-sounding spoken briefing (~55-75 words) that
    never loses specific county names, facility names, street/city locations, or exact numbers,
    and falls back cleanly to `persona_payload["voice_summary"]` if unavailable.
    """
    fallback_script = _clean_for_spoken_readback(
        persona_payload.get("voice_summary") or ""
    )
    if not fallback_script:
        return "Readiness briefing loaded. Check the map and action cards on screen for your county's top priorities."

    county_label = persona_payload.get("county_label") or "Lee County, FL"
    p_info = persona_payload.get("persona_info") or {}
    kpis = persona_payload.get("persona_kpis") or []
    cards = persona_payload.get("action_cards") or []

    kpi_lines = "; ".join(
        f"{k.get('label')}: {k.get('value')} ({k.get('sub')})" for k in kpis[:4]
    )
    card_lines = " | ".join(
        f"{c.get('title')} — {c.get('detail')}" for c in cards[:3]
    )

    prompt = (
        f"You are speaking out loud to an emergency planner or hospital coordinator who just asked:\n"
        f"\"{question}\"\n\n"
        f"Active County: {county_label}\n"
        f"Role Context: {p_info.get('persona_title', '')} — {p_info.get('intent_label', '')}\n"
        f"Base Summary: {fallback_script}\n"
        f"Key County Numbers: {kpi_lines}\n"
        f"Recommended Actions & Specific Facilities: {card_lines}\n\n"
        f"Write a warm, natural, conversational spoken briefing in 3 to 4 sentences (55 to 75 words) "
        f"that directly answers their question. "
        f"CRITICAL RULES:\n"
        f"1. NEVER lose specific details: explicitly state the county name ({county_label}), the exact numbers "
        f"(shelter capacity, carless homes, nursing home beds, or medical power patients), the specific building "
        f"or school or nursing home names, their city or street, and the exact recommended next action.\n"
        f"2. Use plain, everyday spoken English—no bullet points, no markdown, no symbols (*, _, #), "
        f"and no database jargon like FIPS, SLOSH, NULL, or UNRECORDED (say 'storm surge flood zone' or 'missing safety paperwork' instead).\n"
        f"Return ONLY the spoken script text."
    )

    try:
        client = get_genai_client()
        resp = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.25,
                max_output_tokens=220,
            ),
        )
        candidate_text = _clean_for_spoken_readback(resp.text or "")
        if len(candidate_text.split()) >= 20:
            return candidate_text
    except Exception:
        pass

    return fallback_script


def synthesize_natural_speech_wav(
    text: str,
    voice_name: str = "Kore",
) -> Dict[str, Any]:
    """Synthesize natural human-sounding speech audio (WAV base64) using Vertex AI Gemini 2.5 Flash TTS.

    Wraps raw 24,000 Hz 16-bit mono PCM bytes in a standard RIFF WAV header so any browser
    `<audio>` element can play `data:audio/wav;base64,...` natively.
    """
    spoken_text = _clean_for_spoken_readback(text)
    if not spoken_text:
        return {"status": "fallback", "reason": "Empty text provided for TTS."}

    selected_voice = (voice_name or "Kore").strip()
    tts_prompt = (
        "Speak this emergency readiness briefing clearly, warmly, and naturally "
        f"at a steady professional pace:\n\n{spoken_text}"
    )
    tts_config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=selected_voice
                )
            )
        ),
    )

    last_err = ""
    for client_getter in (get_tts_client, get_genai_client):
        for tts_model in ("gemini-2.5-flash-preview-tts", "gemini-2.5-flash-tts"):
            try:
                client = client_getter()
                response = client.models.generate_content(
                    model=tts_model,
                    contents=tts_prompt,
                    config=tts_config,
                )
                candidates = getattr(response, "candidates", None) or []
                if not candidates or not getattr(candidates[0], "content", None):
                    continue
                for part in candidates[0].content.parts or []:
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None):
                        raw_data = inline.data
                        if isinstance(raw_data, str):
                            audio_bytes = base64.b64decode(raw_data)
                        else:
                            audio_bytes = bytes(raw_data)

                        if not audio_bytes:
                            continue

                        # Wrap raw 24kHz 16-bit mono PCM in a standard WAV header if not already RIFF WAV
                        if not audio_bytes.startswith(b"RIFF"):
                            wav_buf = io.BytesIO()
                            with wave.open(wav_buf, "wb") as wf:
                                wf.setnchannels(1)
                                wf.setsampwidth(2)
                                wf.setframerate(24000)
                                wf.writeframes(audio_bytes)
                            audio_bytes = wav_buf.getvalue()

                        b64_str = base64.b64encode(audio_bytes).decode("ascii")
                        return {
                            "status": "ok",
                            "audio_base64": b64_str,
                            "mime_type": "audio/wav",
                            "model_used": tts_model,
                            "voice_name": selected_voice,
                        }
            except Exception as e:
                last_err = str(e)
                continue

    return {
        "status": "fallback",
        "reason": last_err or "Gemini TTS model did not return inline audio bytes.",
    }


def transcribe_voice_audio(
    audio_bytes: bytes,
    mime_type: str = "audio/webm",
) -> str:
    """Transcribe spoken user audio into text using Vertex AI Gemini 2.5 Flash multimodal audio input.

    Args:
        audio_bytes: Raw audio bytes recorded from browser microphone.
        mime_type: Audio MIME type (e.g., 'audio/webm', 'audio/mp4', 'audio/wav').

    Returns:
        Clean transcribed text string.
    """
    client = get_genai_client()
    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
    prompt = (
        "Transcribe the spoken question or command accurately into plain English text. "
        "Context: Florida hurricane evacuation planning across counties (Lee, Miami-Dade, Broward, "
        "Hillsborough, Pinellas, Orange, Duval, Palm Beach, Collier, Sarasota, etc.), shelters, "
        "carless census tracts, transit buses, nursing homes, Medicare DME, oxygen, dialysis, "
        "backup generators. Return ONLY the transcribed text with no extra commentary."
    )
    try:
        resp = client.models.generate_content(
            model=MODEL_NAME,
            contents=[audio_part, prompt],
            config=types.GenerateContentConfig(temperature=0.0),
        )
        return (resp.text or "").strip()
    except Exception:
        resp = client.models.generate_content(
            model=FALLBACK_MODEL_NAME,
            contents=[audio_part, prompt],
            config=types.GenerateContentConfig(temperature=0.0),
        )
        return (resp.text or "").strip()

