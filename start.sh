#!/bin/bash
# Salir inmediatamente si un comando falla
set -e

echo "--- Iniciando Bondiero Bot ---"

# 1. Generar la base de datos SQLite (descarga GTFS y procesa)
echo "--- Generando base de datos estática ---"
python build_db.py

# 2. Iniciar el Bot de Telegram
echo "--- Arrancando el bot ---"
exec python bot.py
