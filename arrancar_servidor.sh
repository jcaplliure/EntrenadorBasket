#!/bin/bash
# Arrancar servidor EntrenadorBasket
cd "$(dirname "$0")"
if [ -d ".venv" ]; then
  .venv/bin/python app.py
else
  echo "No se encontró .venv. Creando entorno virtual..."
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
  .venv/bin/python app.py
fi
