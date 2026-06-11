#!/bin/sh
# Apply migrations, then start the service. event-saver owns the main
# database schema, so the container is the single migration runner.
set -e

alembic upgrade head

exec uvicorn event_saver.main:app --host 0.0.0.0 --port 8888 --log-config uvicorn_config.json
