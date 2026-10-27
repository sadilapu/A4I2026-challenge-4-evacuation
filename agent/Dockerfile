FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

ENV PORT=8080
ENV GOOGLE_CLOUD_PROJECT=qwiklabs-gcp-03-bb316766e33b
ENV GOOGLE_CLOUD_LOCATION=global
ENV GOOGLE_GENAI_USE_VERTEXAI=True
ENV EVAC_AGENT_MODEL=gemini-2.5-flash
ENV DEFAULT_COUNTY_FIPS=12071

EXPOSE 8080

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
