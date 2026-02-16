"""
Configuración de Gunicorn para producción
Compatible con Railway y VPS
"""
import os

# Railway proporciona PORT como variable de entorno
port = os.environ.get("PORT", "8000")
bind = f"0.0.0.0:{port}"

workers = int(os.environ.get("WEB_CONCURRENCY", 2))
worker_class = "sync"
worker_connections = 1000
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
preload_app = True
daemon = False

# Logs a stdout/stderr (Railway los captura automáticamente)
accesslog = "-"
errorlog = "-"
loglevel = "info"
