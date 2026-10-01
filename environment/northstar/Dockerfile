# Northstar runtime image (app and reconciler). Contains no FakePay code.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements/northstar.txt requirements/
RUN pip install --root-user-action=ignore -r requirements/northstar.txt

COPY alembic.ini ./
COPY migrations/ migrations/
COPY northstar/ northstar/

EXPOSE 8000

CMD ["sh", "-c", "python -m northstar.cli init && uvicorn northstar.web.app:create_app --factory --host 0.0.0.0 --port 8000"]
