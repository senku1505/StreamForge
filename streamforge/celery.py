import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'streamforge.settings')

app = Celery('streamforge')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

