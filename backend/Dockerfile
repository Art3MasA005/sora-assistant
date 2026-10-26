# For running the backend on a Linux server/VPS. Windows development runs it directly (see README).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app/backend

COPY backend/pyproject.toml ./
COPY backend/sora ./sora
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
RUN pip install .

RUN useradd --create-home sora && mkdir -p /app/data && chown sora /app/data
USER sora
EXPOSE 8000
CMD ["sh", "-c", "python -m sora migrate && python -m sora serve --host 0.0.0.0"]
