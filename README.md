# Fleet — Autonomous Fleet Management SaaS

Enterprise-grade platform for commercial fleet operations, maintenance, and compliance — built **without real-time hardware, IoT trackers, or GPS integrations**. All data comes from historical records, manual log entries, and uploaded documents (CSV/PDF).

See [CLAUDE.md](./CLAUDE.md) for full project vision, technology stack, architecture, and AI assistant directives.

## Structure

- `backend/` — FastAPI core API (Auth, Vehicles, Manual Logs), SQLAlchemy models, Alembic migrations
- `ai_agents/` — Decoupled LangGraph/MCP agentic framework (FleetCopilot), Pinecone memory, file-parsing tools
- `frontend/` — Next.js (App Router) dashboard
- `prompts.md` — Ongoing AI interaction and prompt log
- `docker-compose.yml` — Local multi-container orchestration

## Status

Initial repository scaffold. Implementation in progress.
