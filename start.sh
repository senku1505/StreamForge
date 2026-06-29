#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "==> Starting Redis server..."
redis-server --daemonize yes

echo "==> Running database migrations..."
python manage.py migrate

echo "==> Starting Celery worker..."
celery -A streamforge worker --loglevel=info --detach

echo "==> Starting Gunicorn server on port 7860..."
exec gunicorn streamforge.wsgi:application --bind 0.0.0.0:7860 --workers 3 --timeout 120
