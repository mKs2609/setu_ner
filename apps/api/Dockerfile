# SetuNER API image. BUILD FROM THE REPO ROOT:
#
#     docker build -f apps/api/Dockerfile -t setuner-api .
#
# The context is the repo root, not apps/api, because the API needs three
# things that live outside its own folder: the trained model artifacts
# (ml/models), the OSM gazetteer (geo/gazetteer) and the SQL migrations
# (infra/migrations). An image built from apps/api alone would start, pass a
# liveness probe, and then fail every forecast and plan request.
#
# The same image runs the web service and the daily job; only the command
# differs (see docs/deployment.md).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SETUNER_MODEL_DIR=/app/artifacts/models \
    SETUNER_GAZETTEER=/app/artifacts/gazetteer/corridor_places.json \
    SETUNER_MIGRATIONS_DIR=/app/artifacts/migrations \
    PORT=8000

WORKDIR /app

# Every dependency ships a manylinux wheel for Python 3.12 (rasterio and
# pyogrio bundle their own GDAL), so no compiler or system GDAL is needed.
# CI builds this image on every push, which is what would catch a dependency
# that stopped shipping one.
COPY apps/api/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY apps/api/app ./app
COPY apps/api/create_tables.py ./create_tables.py
COPY ml/models/*.json ./artifacts/models/
COPY geo/gazetteer/corridor_places.json ./artifacts/gazetteer/
COPY infra/migrations/*.sql ./artifacts/migrations/

# Do not run as root.
RUN useradd --system --uid 10001 --home-dir /app setuner && chown -R setuner /app
USER setuner

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/v1/health', timeout=4)"

# One worker: the corridor road graph is cached per process (~240 MB), so
# each extra worker costs that again. Scale with instances, not workers.
# --proxy-headers because hosting platforms terminate TLS in front of us.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
