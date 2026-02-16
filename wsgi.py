from app import app, db, run_migrations, crear_datos_prueba

with app.app_context():
    run_migrations()
    db.create_all()

if __name__ == "__main__":
    app.run()
