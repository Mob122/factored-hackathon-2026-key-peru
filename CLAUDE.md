# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.


# Factored AI & Data Hackathon 2026 – AI-first banking customer service

Team: Aldair and Martín. Monorepo:
- ml/: Kedro project (data pipelines, models, evaluation). Python 3.11. See ml/CLAUDE.md.
- backend/: API, agent and tools. Loads artifacts produced by ml/, never imports Kedro.
- frontend/: UI.

## Reference docs (read when relevant, don't treat as decided)
- docs/problem_statement.pdf: challenge rules and scoring criteria. Source of truth.
- docs/data_dictionary.pdf: schemas for the 13 tables.
- docs/proposal.md: current plan (v3, replaces v1 and v2). docs/proposal.pdf is the Spanish v1
  draft from before the Day 1 decision.
- ml/docs/hypotheses.md: validation plan and status.

## Decision (final)
Track: card and transaction inquiries assistant (docs/proposal.md v3; rationale in the Amendment
of docs/decision_day1.md). Scope: a Spanish/Portuguese assistant that identifies the card, reads
its status, lists and describes transactions, blocks a card with confirmation and verification,
and hands off to a human with a case file; it only states what it verified in the data.

## Rules
- Never read, print or write AWS credentials. Never read ~/.aws.
- Never commit anything under ml/data/ or any .venv/.
- Work happens on feature branches; never commit to main.
- Output language: code, comments, reports and docs in English.


## Overview

Team "key-peru" entry for the Factored Hackathon 2026: analytics/ML over a synthetic LATAM bank customer-service dataset (complaints, call-center interactions, transactions, etc.). The problem statement, proposal, and data dictionary are PDFs in [docs/](docs/). The working hypotheses and Day 1 query plan (tracks A: unrecognized charges; B: failure demand / resolution time / SLA; C: data quality) live in [ml/docs/hypotheses.md](ml/docs/hypotheses.md).

The repo has three independent sub-projects, each with its own dependencies and run from its own directory:

- `ml/` — Kedro 1.6 project (`banking_cs` package), Python 3.11
- `backend/` — FastAPI + SQLModel API (auth only so far)
- `frontend/` — SvelteKit 2 / Svelte 5 (runes) + Tailwind 4, managed with pnpm

Code identifiers, comments, routes, and UI text are in Spanish (e.g. `usuarios`, `iniciar_sesion`, `correo_electronico`); follow that convention.

## ml/ (Kedro)

Run all commands from `ml/`.

```sh
pip install -r requirements.txt        # plus: pip install -e ".[dev]" for pytest/ruff
kedro run                              # __default__ = sum of all pipelines
kedro run --pipeline data_quality      # a single pipeline
kedro viz                              # pipeline visualization (kedro-viz)
pytest                                 # coverage via pyproject addopts
pytest tests/pipelines/data_quality/test_pipeline.py::test_name
ruff check . && ruff format .
```

- Pipelines are auto-discovered by `find_pipelines(raise_errors=True)` in [pipeline_registry.py](ml/src/banking_cs/pipeline_registry.py): each pipeline is a package under `src/banking_cs/pipelines/<name>/` exposing `create_pipeline()`. Current pipelines (still empty scaffolds): `data_ingestion` → `data_quality` → `intent_model` → `evaluation`.
- Parameters are split per pipeline in `conf/base/parameters_<pipeline>.yml`; datasets go in `conf/base/catalog.yml` (currently empty). Default run env is `local` (see `CONFIG_LOADER_ARGS` in [settings.py](ml/src/banking_cs/settings.py)); `conf/local/` and anything matching `*credentials*` is git-ignored.
- Intended stack for nodes: polars, duckdb, pyarrow (in `requirements.txt`).
- Data follows Kedro layers `data/01_raw` … `data/08_reporting`. Data files are git-ignored (only `.gitkeep` is committed). Raw data in `data/01_raw/`:
  - Flat CSV dimension tables: `customers`, `products`, `branches`, `service_agents`, `marketing_campaigns`, `daily_exchange_rates`.
  - Hive-partitioned daily CSV fact tables: `<table>/year=YYYY/month=MM/day=DD/<table>_YYYYMMDD.csv` for `complaints`, `call_center_interactions`, `call_transcripts`, `campaign_sends`, `digital_events`, `satisfaction_surveys`, `transactions` (2023–2026).
- [tests/test_run.py](ml/tests/test_run.py) is the Kedro template test asserting "Pipeline contains no nodes"; it will fail once pipelines get nodes and should be replaced.

## backend/ (FastAPI)

Run from `backend/`; modules use flat imports (`from db import ...`, `from security import ...`), so the working directory must be `backend/`.

```sh
uvicorn main:app --reload --port 8000
```

- Layering: `routers/` (HTTP, APIRouter) → `services/` (business logic, DB queries) → `models/` (SQLModel tables) with `schemas/` holding Pydantic request/response models. Each package's `__init__.py` re-exports what others import.
- DB session is injected via `SesionDependencia` ([db/config.py](backend/db/config.py)). `DATABASE_URL` is read from `backend/.env` (git-ignored) and is required; SQLite and Postgres/MySQL are both handled. In `ENV=development` (the default) tables are created on startup via `SQLModel.metadata.create_all`; schema changes to existing tables must be added as idempotent SQL in `run_migraciones()`. New model modules must be imported by the `models` package so `create_all` sees them.
- Auth: JWT via PyJWT + pwdlib ([security/config.py](backend/security/config.py)), `SECRET_KEY`/`ALGORITHM` from env. Endpoints under `/autenticacion`: `registrar`, `iniciar-sesion` (returns the raw token string), `mi-perfil`.
- `requirements.txt` does not yet list `sqlmodel`, `pyjwt`, `pwdlib`, `python-dotenv`, or `email-validator`, which the code imports; install them manually or add them.

## frontend/ (SvelteKit)

Run from `frontend/`.

```sh
pnpm install
pnpm dev
pnpm check     # svelte-check type checking
pnpm lint      # prettier --check
pnpm format
```

- The browser never talks to FastAPI directly. [routes/api/auth/+server.ts](frontend/src/routes/api/auth/+server.ts) proxies login/register (`?tipoAuth=login|registrarse`) to `http://localhost:8000` and stores the JWT in an httpOnly `token` cookie.
- [hooks.server.ts](frontend/src/hooks.server.ts) validates the cookie on every request against `/autenticacion/mi-perfil`, sets `event.locals.usuario`, redirects unauthenticated `/app*` requests to `/login`, and redirects signed-in users away from `/login`/`/registrarse`. The root layout load passes `locals` to all pages.
- Route groups: `(auth)/[tipoAuth=tipoAuth]` (param matcher in `src/params/tipoAuth.ts`) serves both `/login` and `/registrarse`; `(app)/app` is the authenticated area. The backend URL is hardcoded as `localhost:8000` in these files.
