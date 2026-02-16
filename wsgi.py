import os
import sys
import logging

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("=== WSGI: Importando app ===")

from werkzeug.middleware.proxy_fix import ProxyFix
from app import app, db, run_migrations

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

port = os.environ.get("PORT", "no definido")
db_url = os.environ.get("DATABASE_URL", "no definido")
logger.info(f"=== WSGI: PORT={port}, DATABASE_URL={'configurado' if db_url != 'no definido' else 'NO configurado (usará SQLite)'} ===")

try:
    with app.app_context():
        logger.info("=== WSGI: Ejecutando db.create_all() ===")
        db.create_all()
        logger.info("=== WSGI: Ejecutando run_migrations() ===")
        run_migrations()
        logger.info("=== WSGI: Base de datos lista ===")
except Exception as e:
    logger.error(f"=== WSGI: Error en BD: {e} ===")

logger.info("=== WSGI: App lista para recibir peticiones ===")

if __name__ == "__main__":
    app.run()
