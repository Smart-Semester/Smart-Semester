# Smart-Semester
Smart Semester is a registration-planning helper for university students. Given a student's degree program and their planned courses for an upcoming semester, the app checks prerequisite/corequisite eligibility and surfaces curated information and resources for each planned course, including course summaries and external prep resources.

# Proposed File Structure
smart-semester/
├── .github/
│   └── workflows/              # CI/CD pipelines (per-service, using path filters)
│       ├── catalog-service.yml
│       ├── resources-service.yml
│       ├── frontend.yml
│       └── infra.yml
├── frontend/                   # Next.js app
│   ├── src/
│   ├── public/
│   ├── Dockerfile
│   ├── package.json
│   └── README.md
├── services/
│   ├── catalog-service/        # FastAPI — courses, prereqs, degree requirements
│   │   ├── app/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── README.md
│   └── resources-service/      # FastAPI — curated links, LLM summaries
│       ├── app/
│       ├── tests/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── README.md
├── ingest/                     # Scraper + manual data entry scripts (feeds catalog-service DB)
│   ├── scraper/
│   ├── seed-data/               # manually entered prose-requirement data
│   └── README.md
├── infra/                      # Docker Compose, GCP configs, Terraform if you use it
│   ├── docker-compose.yml
│   ├── gcp/
│   └── README.md
├── docs/                       # Your planning docs + diagrams
│   ├── PRD.md
│   ├── architecture-diagram.md
│   ├── use-case-diagram.md
│   ├── activity-diagram.md
│   └── decisions.md             # running log of decisions made each week
├── .gitignore
└── README.md                   # top-level: what this is, how to run it locally


