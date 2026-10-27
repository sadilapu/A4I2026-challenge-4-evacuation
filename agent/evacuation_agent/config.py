"""Configuration for the Challenge 4 Adaptive Evacuation Readiness ADK Agent."""

import os

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-bb316766e33b")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
BQ_LOCATION = os.environ.get("BQ_LOCATION", "US")
DATASET = os.environ.get("BQ_DATASET", "evacuation_readiness")

# Ensure Vertex AI environment variables are set for google-genai and google-adk
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROJECT_ID)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", LOCATION)
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

# Primary model verified with Grounding with Google Maps in Vertex AI global
MODEL_NAME = os.environ.get("EVAC_AGENT_MODEL", "gemini-2.5-flash")
FALLBACK_MODEL_NAME = os.environ.get("EVAC_AGENT_FALLBACK_MODEL", "gemini-2.0-flash")

DEFAULT_COUNTY_FIPS = os.environ.get("DEFAULT_COUNTY_FIPS", "12071")  # Lee County, FL
DEFAULT_COUNTY_NAME = os.environ.get("DEFAULT_COUNTY_NAME", "Lee")
DEFAULT_STATE = os.environ.get("DEFAULT_STATE", "FL")
