# 🚌 Bondiero Bot

Un bot de Telegram asíncrono diseñado para informar en tiempo real cuánto tiempo falta para que llegue el próximo colectivo en la Ciudad Autónoma de Buenos Aires (CABA). Optimizado para despliegue eficiente en entornos de bajos recursos (como el plan gratuito de Fly.io).

## 🚀 Inicio Rápido

### Requisitos Previos
- Python 3.11+
- Tokens de la [API de Transporte de CABA](https://www.buenosaires.gob.ar/desarrollourbano/transporte/api-de-transporte) (Client ID y Client Secret).
- Un Token de Bot de Telegram (vía @BotFather).

### Instalación Local
1. Clonar el repositorio.
2. Crear un entorno virtual: `python -m venv venv`.
3. Activar el entorno e instalar dependencias: `pip install -r requirements.txt`.
4. Configurar el archivo `.env`.

### Inicialización de Datos
El bot requiere una base de datos SQLite con las paradas y rutas de CABA. Se genera automáticamente:
```bash
python build_db.py
```

## ✨ Características y Optimizaciones
- **Eficiencia de Memoria:** Procesamiento de GTFS mediante *streaming* (csv nativo) para funcionar en servidores con solo 512MB de RAM.
- **Base de Datos Ultra-Slim:** Reducción de la base de datos de 2GB a ~5MB mediante la selección de viajes representativos, sin pérdida de funcionalidad de paradas.
- **Geolocalización Robusta:** Integración con Nominatim (OpenStreetMap) configurada para evitar bloqueos en servidores de producción.
- **Cálculo de ETA Inteligente:** Intenta calcular la ruta real vía OSRM y cuenta con un *fallback* automático por distancia lineal (18 km/h) si el servicio externo falla.
- **Tiempo Real:** Conexión directa con el feed Protobuf de GTFS-Realtime de CABA.

## ⚙️ Configuración

Crea un archivo `.env` con las siguientes variables:
- `TELEGRAM_TOKEN`: Token de Telegram.
- `CABA_API_CLIENT_ID`: ID de cliente de la API de CABA.
- `CABA_API_CLIENT_SECRET`: Secreto de cliente de la API de CABA.

## 🚀 Despliegue en Fly.io
El proyecto incluye `Dockerfile`, `start.sh` y `fly.toml` listos para usar.

1. `fly auth login`
2. `fly launch` (usar configuración existente)
3. Configurar secretos:
   ```bash
   fly secrets set TELEGRAM_TOKEN=... CABA_API_CLIENT_ID=... CABA_API_CLIENT_SECRET=...
   ```
4. `fly deploy`

*Nota: La base de datos se reconstruye automáticamente en cada despliegue o reinicio para asegurar datos actualizados.*

## 📄 Licencia
Este proyecto se distribuye bajo la licencia MIT.
