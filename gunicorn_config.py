"""
Configuración de Gunicorn para producción
Rutas configuradas para /var/www/basketball-coach (estándar en producción)
"""
import os

# Directorio base de la aplicación
APP_DIR = "/var/www/basketball-coach"

# Configuración del servidor
bind = "127.0.0.1:8000"
workers = 2  # Para 1GB RAM, 2 workers es suficiente
worker_class = "sync"
worker_connections = 1000
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
preload_app = True
daemon = False

# Archivos PID y logs
pidfile = os.path.join(APP_DIR, "gunicorn.pid")
accesslog = os.path.join(APP_DIR, "logs", "access.log")
errorlog = os.path.join(APP_DIR, "logs", "error.log")
loglevel = "info"

# Usuario y grupo (descomentar si es necesario)
# user = "basketballcoach"
# group = "basketballcoach"
