#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "==> Starting Redis server..."
redis-server --daemonize yes

echo "==> Running database migrations..."
python manage.py migrate

echo "==> Running S3 database synchronization and cleanup..."
if [ "$WIPE_STORAGE" = "True" ]; then
    echo "==> Wiping database and S3/R2 storage as requested by WIPE_STORAGE=True..."
    python manage.py shell -c "from django.core.files.storage import default_storage; from django.conf import settings; from videos.models import Video; Video.objects.all().delete(); getattr(default_storage, 'bucket', None) and default_storage.bucket.objects.all().delete()"
fi
python manage.py sync_s3

echo "==> Creating superuser if env variables exist..."
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    python manage.py createsuperuser --noinput || echo "Superuser already exists or creation failed."
fi

echo "==> Collecting static files..."
python manage.py collectstatic --noinput

echo "==> Starting Celery worker..."
celery -A streamforge worker --loglevel=info --detach

echo "==> Starting Gunicorn server on port 7860..."
exec gunicorn streamforge.wsgi:application --bind 0.0.0.0:7860 --workers 3 --timeout 120
