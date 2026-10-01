FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY . .

RUN uv sync --no-dev --no-install-project

EXPOSE 8100
# server.py is the actual HTTP/SSE entrypoint (OrchestratorSession wrapped
# for /chat, see server.py's own docstring) — agents.fleet_copilot is a
# LangGraph builder module with no server of its own, never meant to be run
# directly like this.
CMD ["uv", "run", "--no-sync", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8100"]
