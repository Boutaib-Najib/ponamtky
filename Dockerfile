# Python 3.12 + Playwright Firefox (system deps via Playwright CLI)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install-deps firefox \
    && playwright install firefox

COPY . .

EXPOSE 5009

# One Gunicorn worker avoids N× Firefox stacks; use PLAYWRIGHT_WORKER_THREADS / in-app pool for scrape concurrency.
CMD ["gunicorn", "--bind", "0.0.0.0:5009", "--workers", "1", "--threads", "8", "--timeout", "300", "app:app"]
