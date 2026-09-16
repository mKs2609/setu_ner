---
title: SetuNER API
emoji: 🌉
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# SetuNER API

FastAPI backend for SetuNER — road accessibility forecasting and relief supply
planning for the Barak Valley corridor, Assam (SIH 2026, PS SIH26002).

Code: https://github.com/mKs2609/setu_ner — this Space only holds the
Dockerfile that builds it. Health: `/api/v1/health/ready`. API docs: `/docs`.

Configuration is set as Space **secrets** (never committed):
`ENVIRONMENT`, `DATABASE_URL`, `CORS_ALLOWED_ORIGINS`, `OPERATOR_TOKEN_HASHES`,
`PUBLIC_FIELD_REPORTS`. See `docs/deployment.md` in the code repo.
