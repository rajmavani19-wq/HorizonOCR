"""Gunicorn settings for the private HorizonOCR service."""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
# Keep one worker with SQLite. Migrate to a network database before increasing workers.
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "180"))
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
