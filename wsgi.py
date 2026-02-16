from werkzeug.middleware.proxy_fix import ProxyFix
from app import app, db, run_migrations

# ProxyFix: Railway (y nginx) envían X-Forwarded-Proto y X-Forwarded-For.
# Sin esto, Flask ve http:// en vez de https:// detrás del proxy.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

with app.app_context():
    db.create_all()
    run_migrations()

if __name__ == "__main__":
    app.run()
