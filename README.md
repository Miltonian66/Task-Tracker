# Task Tracker

> Async FastAPI task tracker with a PostgreSQL backend, Redis caching, Alembic migrations, Docker, and CI — built as a focused demonstration of production-minded backend engineering.

[![CI](https://github.com/Miltonian66/Task-Tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/Miltonian66/Task-Tracker/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

A small internal service for tracking team tasks. It exposes a CRUD API and a **controlled status lifecycle** (a state machine that rejects illegal transitions), backed by an async stack and a thin Redis cache layer.

The codebase is intentionally compact, but every component is built the way I would build it in production: explicit error contracts, graceful degradation, schema migrations, and a meaningful test suite.

---

## Highlights

- **Fully async stack** — FastAPI + async SQLAlchemy 2.0 (typed `Mapped[...]` models) over PostgreSQL/asyncpg.
- **Redis caching with graceful degradation** — the list endpoint is cached; if Redis is unreachable, the service transparently falls back to the database instead of failing.
- **Single error envelope** — every error (validation, not-found, conflict, DB failure) is returned in one consistent JSON shape, with a `request_id` correlation token on internal errors.
- **Status state machine** — `todo → in_progress → review → done`, with only single-step forward transitions allowed. Skips, rollbacks, and no-op transitions are rejected with `409`.
- **Alembic migrations** — schema is managed by versioned migrations, not by `create_all()` at startup.
- **28 tests** — endpoint behaviour, validation, the full status lifecycle, pagination bounds, and cache versioning/invalidation, run on an in-memory SQLite + fakeredis harness.
- **Dockerised** — multi-service `docker compose`; the API image runs as a **non-root** user with a `HEALTHCHECK`.
- **CI** — GitHub Actions runs `ruff check`, `ruff format --check`, and `pytest` on every push and PR.

---

## Tech stack

| Layer            | Choice                                                        |
| ---------------- | ------------------------------------------------------------ |
| Language         | Python 3.11+                                                 |
| Web framework    | FastAPI                                                      |
| Data access      | SQLAlchemy 2.0 (async ORM, typed models)                     |
| Database         | PostgreSQL 16 (`asyncpg` driver)                             |
| Cache            | Redis 7 (`redis.asyncio`)                                    |
| Migrations       | Alembic                                                      |
| Validation       | Pydantic v2 / pydantic-settings                             |
| Serialization    | orjson                                                       |
| Tests            | pytest, pytest-asyncio, httpx (ASGI), aiosqlite, fakeredis   |
| Lint / format    | ruff                                                         |
| Packaging        | uv / `pyproject.toml`                                        |
| Runtime / CI     | Docker, docker compose, GitHub Actions                      |

---

## Architecture / request flow

```
                  ┌──────────────────────────────────────┐
                  │            FastAPI app                │
   client ──────▶ │  router → dependency-injected         │
   (HTTP/JSON)    │  session + cache → CRUD layer         │
                  └───────────────┬───────────┬──────────┘
                                  │           │
                       cache hit  │           │  cache miss / writes
                                  ▼           ▼
                          ┌────────────┐  ┌──────────────────┐
                          │   Redis    │  │   PostgreSQL     │
                          │ (list cache│  │ (source of truth)│
                          │  + version)│  │   via asyncpg    │
                          └────────────┘  └──────────────────┘
```

The `GET /tasks` handler checks Redis first; on a miss it queries Postgres and populates the cache. Any write (`POST` / `PATCH` / `DELETE`) bumps a cache **version counter**, which atomically invalidates every cached filter combination at once. If Redis is down, reads and writes still succeed against the database.

---

## Quick start

### With Docker (recommended)

```bash
docker compose up --build
```

This starts three services — `db` (Postgres 16), `redis` (Redis 7), and `api` — with the database and cache gated behind health checks. The `api` service applies migrations (`alembic upgrade head`) before launching the server, so the schema is always up to date. Once they are up, the API is available at:

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- Health: <http://localhost:8000/health>

### Local development

```bash
# 1. Install (uv)
uv sync --extra dev
# ...or with pip:
# pip install -e ".[dev]"

# 2. Configure environment
cp .env.example .env   # adjust DATABASE_URL / REDIS_URL if needed

# 3. Apply migrations
alembic upgrade head

# 4. Run the API
uvicorn app.main:app --reload
```

### Example requests

```bash
# Create a task (starts in `todo`)
curl -sX POST http://localhost:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"Fix sign-up","description":"Crashes on long email","assignee":"m.ivanov"}'

# List in-progress tasks for one assignee
curl -s 'http://localhost:8000/tasks?status=in_progress&assignee=m.ivanov'

# Move a task forward one step
curl -sX PATCH http://localhost:8000/tasks/<UUID>/status \
  -H 'Content-Type: application/json' \
  -d '{"status":"in_progress"}'
```

---

## Migrations (Alembic)

Schema changes are managed by Alembic rather than `Base.metadata.create_all()` at startup. The startup lifespan intentionally does **not** create tables, so production deployments apply schema changes through reviewed, versioned migrations.

Layout:

- `alembic.ini` — configuration (`script_location = app/migrations`).
- `app/migrations/env.py` — async environment; the DSN comes from
  `app.config.get_settings().database_url`, metadata from
  `app.database.Base.metadata`. Migrations live inside the `app` package so
  they ship in the Docker image alongside the code.
- `app/migrations/versions/` — revisions. Initial: `0001_initial`.

```bash
# Apply all migrations
alembic upgrade head

# Autogenerate a new migration after changing the models
alembic revision --autogenerate -m "describe change"

# Roll back the last migration
alembic downgrade -1
```

> The test suite still uses the `create_all()` helper directly to build a throwaway in-memory SQLite schema, so it stays migration-independent and fast.

---

## API endpoints

| Method   | Path                   | Description                                                                 |
| -------- | ---------------------- | --------------------------------------------------------------------------- |
| `POST`   | `/tasks`               | Create a task (starts in `todo`). Returns `201`.                            |
| `GET`    | `/tasks`               | List tasks; filters `status`, `assignee`; pagination `limit`, `offset`.     |
| `GET`    | `/tasks/{id}`          | Fetch a single task by UUID.                                                |
| `PATCH`  | `/tasks/{id}/status`   | Advance the status (strictly to the next step). Returns `409` on a bad move.|
| `DELETE` | `/tasks/{id}`          | Delete a task. Returns `204`.                                               |
| `GET`    | `/health`              | Liveness/readiness probe.                                                   |

**Pagination:** `limit` is an integer `1..500` inclusive (default `100`, enforced as a hard upper bound — exceeding it returns `422`); `offset` is `>= 0`. Lists are ordered by `created_at DESC, id`.

---

## Error format

Every error is returned in a single, predictable envelope:

```json
{
  "error": {
    "code": "invalid_status_transition",
    "message": "Step-skipping is not allowed: 'todo' -> 'done'. The expected next step was 'todo' -> 'in_progress'.",
    "details": { "current": "todo", "requested": "done", "expected": "in_progress" }
  }
}
```

| `code`                       | HTTP | When                                                                                          |
| ---------------------------- | ---- | --------------------------------------------------------------------------------------------- |
| `validation_error`           | 422  | Pydantic rejected the input. `details.errors` lists the offending fields.                     |
| `task_not_found`             | 404  | No task exists for the given `id`.                                                            |
| `invalid_status_transition`  | 409  | Rollback, step-skip, no-op transition, or any move out of the terminal `done` state.          |
| `database_error`             | 500  | Unexpected DB failure. `details.request_id` correlates the response with the server logs; the internal exception type and traceback are never exposed to the client. |

The `request_id` pattern means a user can quote a short token from a 500 response and an operator can grep the logs for the full traceback — without leaking implementation details over the wire.

---

## Status lifecycle

```
todo  ──►  in_progress  ──►  review  ──►  done
```

The status field is a state machine, enforced server-side in the CRUD layer:

1. Only a single forward step to the adjacent status is allowed.
2. Backward transitions (rollbacks) are rejected.
3. Step-skips (`todo → done`, `in_progress → done`, …) are rejected.
4. No-op transitions (setting a task to the status it already has) are rejected — this almost always signals a client bug.
5. `done` is terminal: once reached, no further transitions are permitted.

Each rejection returns `409` with a message and `details` explaining what was requested and which transition (if any) was expected.

---

## Data model

A single `Task` table, with each field choice made deliberately:

| Field         | Type             | Set by  | Rationale                                                                                              |
| ------------- | ---------------- | ------- | ----------------------------------------------------------------------------------------------------- |
| `id`          | `UUID` (v4) PK   | system  | A UUID rather than an auto-increment integer: it leaks no information about table size/insert order and is safe to expose in URLs and logs. |
| `title`       | `str(1..200)`    | client  | Short summary; required, indexed.                                                                     |
| `description` | `str(1..2000)`   | client  | Required (a task with no description is rarely actionable); whitespace-trimmed and rejected if empty. |
| `assignee`    | `str(1..100)`    | client  | A login/username string rather than a foreign-key user id — there is no user table in this MVP, and a string keeps the contract simple while a real user model is specified. Indexed for filtering. |
| `status`      | `enum`           | system  | Non-native enum (`native_enum=False`, stored as a length-bounded string) so the schema is portable across Postgres and SQLite and not tied to a DB-level enum type. Indexed; defaults to `todo`. |
| `created_at`  | `datetime (tz)`  | system  | `server_default now()`. Lets the team spot stale/"stuck" tasks.                                       |
| `updated_at`  | `datetime (tz)`  | system  | `server_default now()` with `onupdate now()`. Surfaces when a task last changed — useful for debugging and audit. |

Both timestamps are timezone-aware. `title`, `assignee`, and `status` are indexed because they are the columns the list endpoint filters and orders on.

---

## Caching

The list endpoint (`GET /tasks`) is cached in Redis with a small TTL; the cache is treated strictly as an optimization, never a source of truth.

- **TTL = 30 seconds.** Short on purpose: it keeps responses reasonably fresh, limits the blast radius of any staleness to a few seconds, and avoids accumulating garbage keys — while still absorbing read bursts on the list endpoint.
- **Versioned invalidation.** Each cache key is namespaced with a global version counter (`tasks:list:version`). Every write performs a single `INCR`, which instantly retires *all* previously cached filter/pagination combinations — no key scanning, no `KEYS *`, no per-filter bookkeeping.
- **Graceful degradation.** Reads and writes wrap Redis access in try/except. If Redis is unreachable at startup, the cache is disabled entirely and the service runs straight against Postgres. A failed read/write is logged at `WARNING` and falls through to the database.
- **The one consistency-sensitive spot is invalidation**: if an `INCR` is lost, stale entries can survive up to the TTL. That single failure mode is logged at `ERROR` (so it can be alerted on in production), and the worst-case staleness is bounded by the TTL.

---

## Testing

```bash
pytest -v
```

The suite (28 tests) runs entirely in-process against an in-memory SQLite database (`aiosqlite` + `StaticPool`) and `fakeredis`, driven through httpx's ASGI transport — no external services required. Coverage includes:

- **Create** — defaults, whitespace trimming, and validation of every field (length bounds, missing/empty/whitespace-only values).
- **Status lifecycle** — valid forward transitions, full `todo → done` flow, and rejection of step-skips, rollbacks, no-ops, exits from `done`, unknown statuses, and changes to missing tasks.
- **List & get** — filtering by `status`/`assignee`, fetch-by-id, 404 handling, and delete.
- **Pagination** — `limit`/`offset` paging, default limit, and boundary enforcement (`0`, negative, above-max, and exactly-at-max).
- **Caching** — that the read path never writes the version key, that invalidation initializes/increments it correctly, and that a write invalidates a previously populated list.

---

## Design decisions & trade-offs

A few things I deliberately left out of this MVP — each is a conscious scope decision, not an oversight:

- **Authentication / authorization.** No requirement specified, and the model needs clarifying first (SSO? JWT?). Adding it before knowing the auth story would just be rework.
- **Status-change history / audit log.** Not required here; straightforward to add later as an append-only table once it is actually needed.
- **Soft delete.** A reasonable future option, but it depends on retention/restore requirements that aren't defined yet, so this MVP does a hard delete.
- **Metrics / tracing.** Prometheus (or VictoriaMetrics) plus distributed tracing is the logical next step, but it is overhead for an MVP of this size and is better added against real production traffic.

The goal was to keep the surface area small while making the parts that *are* here behave like production code.

---

## Project structure

```
.
├── app/
│   ├── api/
│   │   └── tasks.py        # HTTP routes for /tasks
│   ├── migrations/         # Alembic environment + versioned migrations
│   │   ├── env.py          # async migration environment
│   │   └── versions/       # revision scripts (0001_initial, ...)
│   ├── cache.py            # Redis list cache (versioned, graceful degradation)
│   ├── config.py           # pydantic-settings configuration
│   ├── crud.py             # data access + status state-machine enforcement
│   ├── database.py         # async engine/session, Base, create_all helper
│   ├── enums.py            # TaskStatus + transition rules
│   ├── exceptions.py       # error types + unified error-envelope handlers
│   ├── main.py             # app factory + lifespan
│   ├── models.py           # SQLAlchemy 2.0 Task model
│   └── schemas.py          # Pydantic request/response schemas
├── tests/                  # pytest suite (SQLite in-memory + fakeredis)
├── .github/workflows/ci.yml
├── Dockerfile              # non-root image with HEALTHCHECK
├── docker-compose.yml      # db + redis + api
├── alembic.ini
├── pyproject.toml
├── .env.example
└── README.md
```

---

## License

[MIT](./LICENSE) © 2026 Konstantin Fatykov
