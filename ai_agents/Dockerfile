FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY . .

RUN uv sync --no-dev

EXPOSE 8100
CMD ["uv", "run", "python", "-m", "agents.fleet_copilot"]
