# SetuNER API for a Hugging Face Docker Space (free CPU tier: 16 GB RAM).
#
# A Space is its own small git repo, so this Dockerfile does not expect the
# SetuNER code beside it. It fetches the public GitHub repo at build time and
# assembles the same image as apps/api/Dockerfile: the API code, the model
# artifacts, the gazetteer and the migrations.
#
# Copy this file and README.md (from this folder) into the Space repo. See
# docs/deployment.md, "Free path".
#
# PICKING UP NEW COMMITS
# The ADD of the branch's commit feed below changes whenever the branch moves,
# which invalidates Docker's cache from that line on -- so rebuilding the
# Space builds the latest commit rather than a stale clone. The public feed is
# used rather than api.github.com, whose unauthenticated limit (60 requests an
# hour per IP) shared build machines can exhaust.

FROM python:3.12-slim

ARG SETUNER_REPO=https://github.com/mKs2609/setu_ner.git
ARG SETUNER_BRANCH=master

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SETUNER_MODEL_DIR=/app/artifacts/models \
    SETUNER_GAZETTEER=/app/artifacts/gazetteer/corridor_places.json \
    SETUNER_MIGRATIONS_DIR=/app/artifacts/migrations \
    PORT=7860

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Cache-buster: this feed's content changes with every commit to the branch.
ADD https://github.com/mKs2609/setu_ner/commits/${SETUNER_BRANCH}.atom /tmp/setuner-commits.atom

RUN git clone --depth 1 --branch "${SETUNER_BRANCH}" "${SETUNER_REPO}" /src

WORKDIR /app
RUN pip install -r /src/apps/api/requirements.txt

RUN cp -r /src/apps/api/app ./app \
    && mkdir -p artifacts/models artifacts/gazetteer artifacts/migrations \
    && cp /src/ml/models/*.json artifacts/models/ \
    && cp /src/geo/gazetteer/corridor_places.json artifacts/gazetteer/ \
    && cp /src/infra/migrations/*.sql artifacts/migrations/ \
    && git -C /src rev-parse HEAD > /app/COMMIT \
    && rm -rf /src

# Spaces run containers as uid 1000.
RUN useradd -m -u 1000 user && chown -R user /app
USER user

EXPOSE 7860

# One worker: the road graph is cached per process.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
