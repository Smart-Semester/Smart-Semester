# Smart-Semester
Smart Semester is a registration-planning helper for university students. Given a student's degree program and their planned courses for an upcoming semester, the app checks prerequisite/corequisite eligibility and surfaces curated information and resources for each planned course, including course summaries and external prep resources.

# File Structure
- `frontend/` - Next.js app
- `services/catalog-service/` - courses, prereqs, degree requirements (FastAPI)
- `services/resources-service/` - curated resources + LLM summaries (FastAPI)
- `ingest/` - catalog scraper + manual seed data
- `infra/` - Docker, GCP config
- `docs/` - PRD and diagrams
