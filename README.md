# 🚌 Bondiero Bot

Un bot de Telegram asíncrono diseñado para informar en tiempo real cuánto tiempo falta para que llegue el próximo colectivo en la Ciudad Autónoma de Buenos Aires (CABA). Utiliza datos oficiales de GTFS-Realtime y cálculos de ruta precisos.

## 🚀 Inicio Rápido

### Requisitos Previos
- Python 3.10+
- Tokens de la [API de Transporte de CABA](https://www.buenosaires.gob.ar/desarrollourbano/transporte/api-de-transporte) (Client ID y Client Secret).
- Un Token de Bot de Telegram (creado vía @BotFather).

### Instalación
1. Clonar el repositorio.
2. Crear un entorno virtual: `python -m venv venv`.
3. Activar el entorno: `source venv/bin/activate` (Linux/macOS) o `venv\Scripts\activate` (Windows).
4. Instalar dependencias: `pip install -r requirements.txt`.
5. Configurar el archivo `.env` (ver sección de Configuración).

### Inicialización de Datos
Antes de correr el bot por primera vez, debes generar la base de datos local con los datos estáticos de CABA:
```bash
python build_db.py
```

### Ejecución
```bash
python bot.py
```

## ✨ Características
- **Consultas por Línea:** `/132` para buscar paradas cercanas.
- **Búsqueda Directa:** `/132 rivadavia 4296` para obtener tiempos en una dirección específica.
- **Ubicación GPS:** Soporte nativo para compartir ubicación desde Telegram.
- **Tiempo Real:** Conexión con el feed GTFS-RT de CABA.
- **Cálculo de ETA:** Integración con OSRM para estimar minutos de llegada según el tráfico y recorrido.
- **Doble Sentido:** Muestra arribos para ambos sentidos de la línea (Ida y Vuelta).

## ⚙️ Configuración

Crea un archivo `.env` basado en `.env.example`:

| Variable | Descripción |
|----------|-------------|
| `TELEGRAM_TOKEN` | Token de tu bot de Telegram. |
| `CABA_API_CLIENT_ID` | Client ID de la API de Transporte CABA. |
| `CABA_API_CLIENT_SECRET` | Client Secret de la API de Transporte CABA. |

## 🛠️ Arquitectura
- **`build_db.py`**: Descarga el ZIP de GTFS CABA y lo convierte en una base de datos SQLite optimizada con índices.
- **`bot.py`**: Lógica principal del bot (ConversationHandler, Geolocalización con Nominatim, Parsing de Protobuf y ETAs).
- **`transporte.db`**: Base de datos local (generada) para cruzar rutas, paradas y recorridos.

## 🚀 Despliegue (Fly.io)
El proyecto está optimizado para Fly.io. Asegúrate de:
1. Tener instalado `flyctl`.
2. Ejecutar `fly launch`.
3. Configurar los secretos: `fly secrets set TELEGRAM_TOKEN=... CABA_API_CLIENT_ID=... CABA_API_CLIENT_SECRET=...`.
4. El comando de inicio debe incluir la ejecución de `build_db.py` o asegurar que la DB esté presente.

## 📄 Licencia
Este proyecto se distribuye bajo la licencia MIT.
