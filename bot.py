import os
import logging
import sqlite3
import math
import aiohttp
import asyncio
from dotenv import load_dotenv
from geopy.geocoders import Nominatim
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from google.transit import gtfs_realtime_pb2

# Configuración
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CLIENT_ID = os.getenv("CABA_API_CLIENT_ID")
CLIENT_SECRET = os.getenv("CABA_API_CLIENT_SECRET")
DB_NAME = "transporte.db"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Estados del ConversationHandler
WAITING_LOCATION = 1

# --- Utilidades Geográficas ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Radio de la Tierra en km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# --- Lógica de Base de Datos ---
def get_nearest_stops(route_short_name, user_lat, user_lon):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT route_id, route_short_name FROM routes WHERE route_short_name = ? OR route_short_name LIKE ?", (route_short_name, route_short_name + "%"))
    routes = cursor.fetchall()
    
    if not routes:
        conn.close()
        return []
    
    valid_route_ids = []
    for rid, rname in routes:
        if rname == route_short_name or (len(rname) > len(route_short_name) and rname[len(route_short_name)].isalpha()):
            valid_route_ids.append(rid)

    if not valid_route_ids:
        conn.close()
        return []

    placeholders = ",".join(["?"] * len(valid_route_ids))
    query = f"""
    SELECT DISTINCT s.stop_id, s.stop_name, s.stop_lat, s.stop_lon, t.direction_id, r.route_id, t.trip_headsign
    FROM stops s
    JOIN stop_times st ON s.stop_id = st.stop_id
    JOIN trips t ON st.trip_id = t.trip_id
    JOIN routes r ON t.route_id = r.route_id
    WHERE r.route_id IN ({placeholders})
    """
    cursor.execute(query, valid_route_ids)
    stops = cursor.fetchall()
    conn.close()

    if not stops:
        return []

    # Filtrar paradas a menos de 5km
    nearby_stops = [s for s in stops if haversine(user_lat, user_lon, s[2], s[3]) < 5.0]

    if not nearby_stops:
        return []

    dir_0 = [s for s in nearby_stops if s[4] == 0]
    dir_1 = [s for s in nearby_stops if s[4] == 1]
    
    best_stops = []
    if dir_0:
        nearest_0 = min(dir_0, key=lambda s: haversine(user_lat, user_lon, s[2], s[3]))
        best_stops.append({
            "stop_id": nearest_0[0], "stop_name": nearest_0[1], "lat": nearest_0[2], 
            "lon": nearest_0[3], "direction_id": nearest_0[4], "route_id": nearest_0[5], "headsign": nearest_0[6]
        })
    if dir_1:
        nearest_1 = min(dir_1, key=lambda s: haversine(user_lat, user_lon, s[2], s[3]))
        best_stops.append({
            "stop_id": nearest_1[0], "stop_name": nearest_1[1], "lat": nearest_1[2], 
            "lon": nearest_1[3], "direction_id": nearest_1[4], "route_id": nearest_1[5], "headsign": nearest_1[6]
        })
    return best_stops

# --- Integración con APIs ---
async def fetch_realtime_data(route_ids):
    url = "https://apitransporte.buenosaires.gob.ar/colectivos/vehiclePositions"
    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    
    route_ids_str = [str(r) for r in route_ids]
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status != 200:
                    logger.error(f"Error API CABA ({resp.status})")
                    return []
                content = await resp.read()
                
                feed = gtfs_realtime_pb2.FeedMessage()
                feed.ParseFromString(content)
                
                vehicles = []
                for entity in feed.entity:
                    if entity.HasField('vehicle'):
                        v_route_id = str(entity.vehicle.trip.route_id)
                        if v_route_id in route_ids_str:
                            vehicles.append({
                                'route_id': v_route_id,
                                'latitude': entity.vehicle.position.latitude,
                                'longitude': entity.vehicle.position.longitude
                            })
                return vehicles
        except Exception as e:
            logger.error(f"Error en fetch_realtime_data: {type(e).__name__}: {e}")
            return []

async def calculate_eta(bus_lat, bus_lon, stop_lat, stop_lon):
    url = f"http://router.project-osrm.org/route/v1/driving/{bus_lon},{bus_lat};{stop_lon},{stop_lat}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params={"overview": "false"}, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("routes"):
                        duration_sec = data["routes"][0]["duration"]
                        return round(duration_sec / 60)
        except Exception:
            pass
    return None

# --- Handlers del Bot ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Hola! Soy Bondiero Bot 🚌.\nEnviame el número de línea (ej: /152) o con dirección (ej: /152 rivadavia 4296).")

async def handle_line_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = text.split(maxsplit=1)
    line = parts[0].replace("/", "").strip()
    context.user_data["current_line"] = line
    
    if len(parts) > 1:
        address = parts[1]
        await update.message.reply_text(f"Buscando '{address}' en CABA...")
        # Usamos un User-Agent único y tiempo de espera de 10s para evitar bloqueos
        geolocator = Nominatim(user_agent="bondiero_bot_alexis_prod_v2")
        try:
            # Fuerza a CABA
            location = geolocator.geocode(
                f"{address}, Ciudad Autónoma de Buenos Aires, Argentina", 
                timeout=10
            )
            if location:
                return await process_location(update, context, location.latitude, location.longitude)
            else:
                await update.message.reply_text("No encontré esa dirección en CABA. Enviame tu ubicación GPS.")
        except Exception as e:
            if "malformed" in str(e):
                logger.error(f"Error Crítico Base de Datos: {e}")
                await update.message.reply_text("Error en la base de datos del servidor. Reintentando...")
            else:
                logger.error(f"Error Geocoder: {e}")
                await update.message.reply_text("Error al buscar dirección. Enviame tu ubicación GPS.")

    await update.message.reply_text(
        f"¿Donde estas? Enviame tu ubicación para buscar las paradas del {line}.",
        reply_markup=ReplyKeyboardMarkup([[{ "text": "Enviar Ubicación 📍", "request_location": True }]], one_time_keyboard=True)
    )
    return WAITING_LOCATION

async def process_location_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_location = update.message.location
    return await process_location(update, context, user_location.latitude, user_location.longitude)

async def process_location(update: Update, context: ContextTypes.DEFAULT_TYPE, lat, lon):
    line = context.user_data.get("current_line")
    await update.message.reply_text(f"Buscando paradas cercanas del {line}...", reply_markup=ReplyKeyboardRemove())
    
    stops = get_nearest_stops(line, lat, lon)
    if not stops:
        await update.message.reply_text(f"No encontré paradas para la línea {line} cerca de tu posición (radio 5km).")
        return ConversationHandler.END

    route_ids = list(set([s["route_id"] for s in stops]))
    vehicles = await fetch_realtime_data(route_ids)
    
    if not vehicles:
        await update.message.reply_text("No hay unidades de esta línea reportando posición en este momento.")
        return ConversationHandler.END

    response_text = f"🚌 *Línea {line}*\n\n"
    
    for stop in stops:
        headsign_clean = stop['headsign'].title() if stop['headsign'] else "Destino Desconocido"
        response_text += f"📍 *Hacia {headsign_clean}*\nParada: {stop['stop_name']}\n"
        
        # Filtrar vehiculos de esta ruta
        route_vehicles = [v for v in vehicles if v['route_id'] == str(stop['route_id'])]
        
        # Calcular distancias y tomar los 3 más cercanos a la parada
        for v in route_vehicles:
            v['dist'] = haversine(v['latitude'], v['longitude'], stop["lat"], stop["lon"])
        
        # Filtrar colectivos muy lejanos (ej: a mas de 10km) para no calcular ETA de colectivos de otra zona
        route_vehicles = [v for v in route_vehicles if v['dist'] < 10.0]
        route_vehicles = sorted(route_vehicles, key=lambda x: x['dist'])[:3]
        
        if not route_vehicles:
            response_text += "No hay colectivos acercándose.\n\n"
            continue
            
        tasks = [calculate_eta(v['latitude'], v['longitude'], stop["lat"], stop["lon"]) for v in route_vehicles]
        results = await asyncio.gather(*tasks)
        etas = sorted([r for r in results if r is not None])
        
        if not etas:
            response_text += "Calculando tiempo...\n\n"
        else:
            proximos = ", ".join([f"{e} min" for e in etas])
            response_text += f"Llegan en: *{proximos}*\n\n"

    await update.message.reply_markdown(response_text)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operación cancelada.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

def main():
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_TOKEN no configurado.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    line_filter = filters.Regex(r"^/\d+")

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(line_filter, handle_line_command)],
        states={
            WAITING_LOCATION: [
                MessageHandler(filters.LOCATION, process_location_update),
                MessageHandler(line_filter, handle_line_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_line_command)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    print("Bondiero Bot iniciado...")
    application.run_polling()

if __name__ == "__main__":
    main()