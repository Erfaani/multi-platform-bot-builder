FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev gettext curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements/ /app/requirements/
ARG REQUIREMENTS=local.txt
RUN pip install -r /app/requirements/${REQUIREMENTS}

# Run as a non-root user.
RUN useradd --create-home --uid 1000 appuser
COPY --chown=appuser:appuser backend/ /app/
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
