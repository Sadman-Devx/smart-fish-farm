web: gunicorn smart_fish_farm.wsgi:application --bind 0.0.0.0:${PORT}
worker: celery -A smart_fish_farm worker --loglevel=info
beat: celery -A smart_fish_farm beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler