# Catalog Service

The Catalog Service provides official course information (titles, descriptions, structured prerequisite and corequisite trees) to the Planner and other services via a REST API.

For a practical integration walkthrough, see the
[Catalog API consumer guide](../../docs/Catalog-Service-Consumer-Guide.md).

## API Contract

Implements the contract defined in [`docs/Catalog-API-Contract.md`](../../docs/Catalog-API-Contract.md):

- `GET /courses?codes=CS3358&codes=CS1428`
  - Accepts between 1 and 20 `codes` query parameters (uppercase, no spaces).
  - Returns a JSON array of `CatalogResponse` objects.
  - Unknown course codes are omitted from the response array (not a 404).
- `GET /health` — Liveness probe (returns `{"status": "ok"}`).
- `GET /ready` — Readiness probe verifying active database connection (returns `{"status": "ready"}` or 503 if unreachable).

## Requirements

- Python 3.11+
- PostgreSQL (running with migrations `01` through `06` applied)

## Local Development

```bash
# From services/catalog-service:
pip install -r requirements.txt

# Set the database URL
export DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester"

# Start the server on port 8001
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

## Running Tests

Offline unit tests (mock database, no live Postgres required):

```bash
pytest tests/ -v
```
