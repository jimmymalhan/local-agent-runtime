# {{name}}

FastAPI REST API with async SQLAlchemy, Alembic migrations, and Docker.

## Quick start

```bash
# 1. Copy .env.example and configure
cp .env.example .env

# 2. Start services
docker compose up -d

# 3. Run migrations
alembic upgrade head

# 4. Visit API docs
open http://localhost:8000/api/v1/docs
```

## Development

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Tests

```bash
pytest --asyncio-mode=auto -v
```

## Project structure

```
app/
  main.py          # FastAPI app, lifespan, CORS, error handlers
  api/v1/          # Versioned API routers and endpoints
  models/          # SQLAlchemy ORM models
  schemas/         # Pydantic request/response schemas
  core/            # Settings and database engine
  deps.py          # FastAPI dependency injection
alembic/           # Database migrations
tests/             # pytest-asyncio test suite
Dockerfile         # Multi-stage build
docker-compose.yml # App + PostgreSQL
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | sqlite+aiosqlite (tests) | Async DB URL |
| `SECRET_KEY` | change-me | JWT signing key |
| `ENVIRONMENT` | development | development / production |
| `ALLOWED_ORIGINS` | localhost:3000 | CORS origins |
