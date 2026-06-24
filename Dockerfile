# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Keep build tooling current so editable install resolves cleanly.
RUN pip install --upgrade pip setuptools wheel

# Copy source (editable install keeps __file__ rooted in this tree).
COPY . .

RUN pip install -e .

# Default to production-ish runtime env; secrets come from .env / compose.
ENV ENVIRONMENT=prod \
    LOG_LEVEL=INFO

# Long polling by default: no ports exposed. Webhook mode (later step)
# will expose 8080 for the FastAPI process.
CMD ["python", "-m", "app.main"]
