# Guía de Despliegue en VPS Arsys - Ubuntu 24.04

**Ejecuta todos los comandos como `root`**

---

## 1. Instalar Dependencias

```bash
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv python3-dev nginx git
apt install -y libjpeg-dev zlib1g-dev libpng-dev libfreetype6-dev

# Configurar firewall
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw enable
```

---

## 2. Crear Usuario y Directorios

```bash
# Crear usuario
adduser --disabled-password --gecos "" basketballcoach

# Crear directorios
mkdir -p /var/www/basketball-coach/logs
mkdir -p /var/www/basketball-coach/static/uploads
chown -R basketballcoach:basketballcoach /var/www/basketball-coach
chmod -R 755 /var/www/basketball-coach
```

---

## 3. Subir el Proyecto

### Opción A: Git con Deploy Key (Recomendado)

```bash
# Generar clave SSH
mkdir -p ~/.ssh
ssh-keygen -t ed25519 -C "deploy" -f ~/.ssh/basketball_coach_deploy -N ""
cat ~/.ssh/basketball_coach_deploy.pub
```

**Añadir la clave pública en GitHub:** Repositorio → Settings → Deploy keys → Add deploy key

```bash
# Configurar SSH
nano ~/.ssh/config
```

**Añadir:**
```
Host github-basketball-coach
    HostName github.com
    User git
    IdentityFile ~/.ssh/basketball_coach_deploy
    IdentitiesOnly yes
```

```bash
chmod 600 ~/.ssh/config

# Clonar repositorio
cd /var/www/basketball-coach
git clone git@github-basketball-coach:TU_USUARIO/basketball-coach.git .
chown -R basketballcoach:basketballcoach /var/www/basketball-coach
```

### Opción B: Subir archivos directamente

Usa SCP, SFTP o FileZilla para subir los archivos a `/var/www/basketball-coach/`

---

## 4. Configurar la Aplicación

```bash
cd /var/www/basketball-coach

# Crear entorno virtual
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

# Crear archivo .env
cp .env.example .env
nano .env
```

**Configurar mínimo en `.env`:**
```bash
SECRET_KEY=genera_una_clave_secreta_aqui
GOOGLE_REDIRECT_URI=https://tu-dominio.com/auth/callback
SESSION_COOKIE_SECURE=True
```

**Generar SECRET_KEY:**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

```bash
# Ajustar permisos
chown -R basketballcoach:basketballcoach /var/www/basketball-coach

# Inicializar base de datos
venv/bin/python3 << EOF
from app import app, db, crear_datos_prueba
with app.app_context():
    db.create_all()
    crear_datos_prueba()
    print("Base de datos inicializada")
EOF
```

---

## 5. Configurar Gunicorn

El archivo `gunicorn_config.py` ya está configurado. Solo verificar:

```bash
# Probar Gunicorn
cd /var/www/basketball-coach
venv/bin/gunicorn --config gunicorn_config.py wsgi:app
# Presionar Ctrl+C para detener
```

---

## 6. Configurar Nginx

```bash
nano /etc/nginx/sites-available/basketball-coach
```

**Contenido (reemplazar `tu-dominio.com`):**
```nginx
server {
    listen 80;
    server_name tu-dominio.com www.tu-dominio.com;
    client_max_body_size 50M;

    location /static {
        alias /var/www/basketball-coach/static;
        expires 30d;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/basketball-coach /etc/nginx/sites-enabled/

# Deshabilitar sitio por defecto de Nginx
rm /etc/nginx/sites-enabled/default

nginx -t
systemctl restart nginx
systemctl enable nginx
```

---

## 7. Configurar Systemd (Servicio)

```bash
nano /etc/systemd/system/basketball-coach.service
```

**Contenido:**
```ini
[Unit]
Description=Basketball Coach Gunicorn
After=network.target

[Service]
User=basketballcoach
Group=basketballcoach
WorkingDirectory=/var/www/basketball-coach
Environment="PATH=/var/www/basketball-coach/venv/bin"
ExecStart=/var/www/basketball-coach/venv/bin/gunicorn --config /var/www/basketball-coach/gunicorn_config.py wsgi:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable basketball-coach
systemctl start basketball-coach
systemctl status basketball-coach
```

---

## 8. Configurar SSL (HTTPS)

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d tu-dominio.com -d www.tu-dominio.com
```

---

## ✅ Verificación

```bash
# Ver estado del servicio
systemctl status basketball-coach

# Ver logs
journalctl -u basketball-coach -f

# Reiniciar si es necesario
systemctl restart basketball-coach
```

---

## 🔄 Actualizar la Aplicación

```bash
cd /var/www/basketball-coach

# Actualizar código
git pull origin main

# Si añadiste nuevas dependencias en requirements.txt:
venv/bin/pip install -r requirements.txt

# Ajustar permisos
chown -R basketballcoach:basketballcoach /var/www/basketball-coach

# Reiniciar servicio
systemctl restart basketball-coach

# Verificar estado
systemctl status basketball-coach
```

**Si cambiaste la estructura de la base de datos:**
```bash
venv/bin/python3 << EOF
from app import app, db
with app.app_context():
    db.create_all()
EOF
systemctl restart basketball-coach
```

---

## 🚨 Solución de Problemas

**Error 502:** Verificar que Gunicorn esté corriendo: `systemctl status basketball-coach`

**Error de permisos:** `chown -R basketballcoach:basketballcoach /var/www/basketball-coach`

**Error "no such table":** Inicializar base de datos (ver sección 4)

**Timeout al acceder:** Verificar firewall: `ufw status` y abrir puerto 80: `ufw allow 80/tcp`

**Ver logs:** `journalctl -u basketball-coach -n 50` o `tail -50 /var/www/basketball-coach/logs/error.log`

**Nginx muestra página por defecto:** Deshabilitar sitio default: `rm /etc/nginx/sites-enabled/default && systemctl restart nginx`
