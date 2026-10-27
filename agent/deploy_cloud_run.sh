#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-qwiklabs-gcp-03-bb316766e33b}"
REGION="${CLOUD_RUN_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-evacuation-readiness-agent}"

echo "Deploying ${SERVICE_NAME} to Cloud Run in project ${PROJECT_ID} (${REGION})..."
gcloud run deploy "${SERVICE_NAME}" \
  --source "$(dirname "$0")" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --min-instances=1 \
  --memory=1Gi \
  --cpu=2 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=global,GOOGLE_GENAI_USE_VERTEXAI=True,EVAC_AGENT_MODEL=gemini-2.5-flash,DEFAULT_COUNTY_FIPS=12071"
