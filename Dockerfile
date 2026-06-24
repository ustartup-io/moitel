# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first (better layer caching).
COPY pyproject.toml MANIFEST.in ./
COPY app/ app/
COPY routers/ routers/
COPY services/ services/
COPY db/ db/
COPY middlewares/ middlewares/
COPY states/ states/
COPY utils/ utils/
COPY texts/ texts/
COPY faq/ faq/
COPY alembic.ini ./
COPY db/migrations/ db/migrations/

RUN pip install --upgrade pip && pip install -e .

# Create non-root user.
RUN useradd -r -s /bin/false botuser && chown -R botuser:botuser /app
USER botuser

# Default env.
ENV ENVIRONMENT=prod \
    LOG_LEVEL=INFO

# Entrypoint: run migrations, then start bot.
CMD ["sh", "-c", "alembic upgrade head && python -m app.main"]
