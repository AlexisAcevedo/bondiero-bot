# 🚌 Bondiero Bot

Bot de Telegram asíncrono que informa en tiempo real cuánto falta para el próximo colectivo en CABA. Optimizado para entornos de bajos recursos (Fly.io free tier, 512MB RAM).

## 🚀 Inicio Rápido

### Requisitos
- Python 3.11+
- Tokens de la [API de Transporte de CABA](https://www.buenosaires.gob.ar/desarrollourbano/transporte/api-de-transporte) (Client ID y Secret)
- Token de Bot de Telegram (vía [@BotFather](https://t.me/BotFather))

### Instalación
```bash
git clone https://github.com/AlexisAcevedo/bondiero-bot.git
cd bondiero-bot
python -m venv venv
pip install -r requirements.txt
```

### Configuración
Crear archivo `.env`:
```env
TELEGRAM_TOKEN=tu_token_de_telegram
CABA_API_CLIENT_ID=tu_client_id
CABA_API_CLIENT_SECRET=tu_client_secret
```

### Generar Base de Datos
```bash
python build_db.py
```
Descarga el GTFS estático de CABA y crea `transporte.db` con paradas, rutas y viajes representativos.

### Ejecutar
```bash
python bot.py
```

## 💬 Uso en Telegram

| Comando | Ejemplo | Descripción |
|---------|---------|-------------|
| `/inicio` | `/start` | Mensaje de bienvenida |
| `/<línea>` | `/152` | Consulta por ubicación GPS |
| `/<línea> <dirección>` | `/132 rivadavia 4296` | Consulta por dirección en CABA |
| `/cancel` | `/cancel` | Cancelar operación |

### Ejemplo de Respuesta

```
🚌 Línea 132

📍 Hacia A Retiro
Parada: 4210 YRIGOYEN HIPOLITO AV. (0.1 km)
⏱ Llegan en: 7 min, 14 min

📍 Hacia A Cement. De Flores X Av. Carabobo
Parada: 4121 RIVADAVIA AV. (0.2 km)
📐 Estimado: 12 min, 18 min
```

- **⏱** = Tiempo real (fuente: `tripUpdates` de la API CABA)
- **📐** = Estimado (calculado desde posiciones GPS de los colectivos)

## 🏗️ Arquitectura

### Motor de ETA (Cascading Fallback)

```
1. tripUpdates (real-time)     ← Predicciones del sistema AVL de cada empresa
   └─ Geographic matching (500m) para resolver formato de stop_id
2. vehiclePositions (fallback) ← Posiciones GPS de los colectivos
   ├─ Filtrado por direction_id (evita duplicados entre ida/vuelta)
   ├─ Deduplicación por vehicle.id
   └─ ETA calculado por:
       a) Velocidad reportada (speed / distancia)
       b) OSRM routing (auto, como proxy)
       c) Distancia lineal a 18 km/h
```

### Endpoints de la API de CABA Utilizados

| Endpoint | Formato | Uso |
|----------|---------|-----|
| `/colectivos/tripUpdates` | Protobuf | ETA primario (arrival_time por parada) |
| `/colectivos/vehiclePositions` | Protobuf | Fallback (lat/lon/speed de cada colectivo) |
| `/colectivos/feed-gtfs` | ZIP | Datos estáticos (rutas, paradas, viajes) |

### Base de Datos (`transporte.db`)

Generada por `build_db.py` desde el GTFS estático. Solo guarda un viaje representativo por (ruta, dirección) para mantener el tamaño bajo (~100MB vs 2GB original).

| Tabla | Contenido |
|-------|-----------|
| `routes` | Líneas de colectivo (route_id, short_name) |
| `trips` | Un viaje por (ruta, dirección) con headsign |
| `stops` | Paradas con coordenadas (lat, lon) |
| `stop_times` | Secuencia de paradas por viaje |

### Stack Técnico

| Componente | Tecnología |
|------------|------------|
| Bot Framework | python-telegram-bot 21.10 |
| HTTP Async | aiohttp |
| Geocoding | geopy (Nominatim/OSM) |
| GTFS-RT | gtfs-realtime-bindings (Protobuf) |
| Base de Datos | SQLite |
| ETA Routing | OSRM (fallback) |
| Deploy | Docker → Fly.io (GRU, 512MB) |

## ✨ Características

- **ETA en Tiempo Real:** `tripUpdates` como fuente primaria con fallback inteligente
- **Filtrado por Dirección:** Muestra colectivos de ida y vuelta por separado, sin duplicados
- **Eficiencia de Memoria:** Procesamiento GTFS con streaming CSV para 512MB RAM
- **Geolocalización Robusta:** Nominatim con geocoding restringido a CABA
- **Matching Geográfico:** Resuelve diferencias de formato entre stop_ids de la DB y la API

## 🚀 Despliegue en Fly.io

```bash
fly auth login
fly launch                    # usar configuración existente
fly secrets set TELEGRAM_TOKEN=... CABA_API_CLIENT_ID=... CABA_API_CLIENT_SECRET=...
fly deploy
```

La base de datos se reconstruye automáticamente en cada deploy (`start.sh` ejecuta `build_db.py` antes de `bot.py`).

## 🧪 Tests

```bash
python test_eta.py            # Integration tests (requiere API keys y transporte.db)
```

Valida: helpers de ETA, matching geográfico de tripUpdates, filtrado por dirección de vehiclePositions, y flujo completo end-to-end.

## 📁 Estructura del Proyecto

```
bondiero-bot/
├── bot.py              # Bot principal + motor de ETA
├── build_db.py         # Generador de base de datos GTFS
├── test_eta.py         # Tests de integración
├── requirements.txt    # Dependencias Python
├── Dockerfile          # Imagen Docker
├── fly.toml            # Configuración Fly.io
├── start.sh            # Script de inicio (build_db + bot)
├── .env.example        # Template de variables de entorno
└── artifacts/          # Documentación de cambios
```

## 📄 Licencia

MIT
