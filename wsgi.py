import os
import sys
import logging

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("=== WSGI: Importando app ===")

from werkzeug.middleware.proxy_fix import ProxyFix
from app import app, db, run_migrations, crear_datos_prueba, TagGroup, Tag

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
        logger.info("=== WSGI: Limpiando duplicados si existen ===")
        seen_groups = {}
        for g in TagGroup.query.order_by(TagGroup.id).all():
            if g.name in seen_groups:
                Tag.query.filter_by(group_id=g.id).delete()
                db.session.delete(g)
            else:
                seen_groups[g.name] = g.id
        db.session.commit()
        seen_tags = {}
        for t in Tag.query.order_by(Tag.id).all():
            if t.name in seen_tags:
                db.session.delete(t)
            else:
                seen_tags[t.name] = t.id
        db.session.commit()
        logger.info("=== WSGI: Creando datos iniciales (etiquetas, grupos) ===")
        crear_datos_prueba()
        logger.info("=== WSGI: Base de datos lista ===")
except Exception as e:
    logger.error(f"=== WSGI: Error en BD: {e} ===")

logger.info("=== WSGI: App lista para recibir peticiones ===")

if __name__ == "__main__":
    app.run()
