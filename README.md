# Smart-Semester
Smart Semester is a registration-planning helper for university students. Given a student's degree program and their planned courses for an upcoming semester, the app checks prerequisite/corequisite eligibility and surfaces curated information and resources for each planned course, including course summaries and external prep resources.

# File Structure
- `frontend/` - Next.js app
- `services/catalog-service/` - courses, prereqs, degree requirements (FastAPI)
- `services/resources-service/` - curated resources + LLM summaries (FastAPI)
- `services/planner-service/` - checks prereqs, parses transcripts (FastAPI)
- `ingest/` - catalog scraper + manual seed data
- `infra/` - Docker, GCP config
- `docs/` - PRD and diagrams

## Local Catalog API

The local database and Catalog API run with Docker Compose. Each developer gets
their own local database; Compose does not share database contents between
machines. After cloning the repository, start the services with:

```bash
docker compose up --build -d
```

Follow the [Local End-to-End Runbook](docs/Local-E2E-Runbook.md) to apply
migrations, ingest syllabus data locally, populate the canonical course catalog
if needed, and verify the API. Syllabus ingestion and canonical course/prerequisite
data are separate steps. Once running, the Catalog API is available at
`http://localhost:8001` (`/health`, `/ready`, and `/courses`). The Compose
database password is for local development only; do not use it as a production
credential.
