# AI-Powered Access Request Classifier

An Identity Governance and Administration (IGA) component that accepts free-text access requests, classifies them into structured types, maps them to roles from a synthetic catalog, computes an anomaly score against the requester's history, recommends an approver, and routes to auto-approval or manual review.

## Quickstart

1. Clone the repository.
2. Copy `.env.example` to `.env` and fill in the required environment variables (e.g., `LLM_API_KEY`).
3. Run `docker compose up`.
4. The application will be available at `http://localhost:8000`. Seed data is loaded automatically.

## Stack

- Python, FastAPI, PostgreSQL, SQLAlchemy
- Structured output classification via a hosted LLM (provider-agnostic adapter)
- HTMX-based UI for end users and reviewers
- Docker Compose for local orchestration

## Documentation

See the [PRD](./tasks/prd-access-request-classifier.md) for full requirements and design decisions.
