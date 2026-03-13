import os
import logging
import sqlite3
import math
import time
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

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CLIENT_ID = os.getenv("CABA_API_CLIENT_ID")
CLIENT_SECRET = os.getenv("CABA_API_CLIENT_SECRET")
DB_NAME = "transporte.db"
API_BASE = "https://apitransporte.buenosaires.gob.ar"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

WAITING_LOCATION = 1


# --- Geographic Utilities ---

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# --- Database Logic ---

def get_nearest_stops(route_short_name, user_lat, user_lon):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT route_id, route_short_name FROM routes WHERE route_short_name = ? OR route_short_name LIKE ?",
        (route_short_name, route_short_name + "%"),
    )
    routes = cursor.fetchall()

    if not routes:
        conn.close()
        return []

    valid_route_ids = []
    for rid, rname in routes:
        if rname == route_short_name or (
            len(rname) > len(route_short_name) and rname[len(route_short_name)].isalpha()
        ):
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

    nearby_stops = [s for s in stops if haversine(user_lat, user_lon, s[2], s[3]) < 5.0]
    if not nearby_stops:
        return []

    dir_0 = [s for s in nearby_stops if s[4] == 0]
    dir_1 = [s for s in nearby_stops if s[4] == 1]

    best_stops = []
    for direction_stops in [dir_0, dir_1]:
        if direction_stops:
            nearest = min(direction_stops, key=lambda s: haversine(user_lat, user_lon, s[2], s[3]))
            best_stops.append({
                "stop_id": nearest[0],
                "stop_name": nearest[1],
                "lat": nearest[2],
                "lon": nearest[3],
                "direction_id": nearest[4],
                "route_id": nearest[5],
                "headsign": nearest[6],
            })
    return best_stops


# --- API Integration ---

async def fetch_trip_updates(route_ids, stops):
    """Fetch real-time trip updates from CABA API.

    Uses geographic matching: for each target stop, finds the closest API stop
    within 500m and uses its arrival time. This handles stop_id format mismatches.

    Returns dict: {stop_id: [arrival_minutes, ...]}
    """
    url = f"{API_BASE}/colectivos/tripUpdates"
    params = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    route_ids_str = {str(r) for r in route_ids}
    now = time.time()

    # Load all stop coordinates from DB for geographic matching
    stop_coords = {}
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT stop_id, stop_lat, stop_lon FROM stops")
        for row in cursor.fetchall():
            stop_coords[str(row[0])] = (row[1], row[2])
        conn.close()
    except Exception as e:
        logger.error(f"Error loading stop coords: {e}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    logger.warning(f"tripUpdates HTTP {resp.status}")
                    return {}

                content = await resp.read()
                feed = gtfs_realtime_pb2.FeedMessage()
                feed.ParseFromString(content)

                # Collect all future arrivals per (route_id, direction_id, api_stop_id)
                arrivals = {}
                for entity in feed.entity:
                    if not entity.HasField("trip_update"):
                        continue
                    tu = entity.trip_update
                    rid = str(tu.trip.route_id)
                    if rid not in route_ids_str:
                        continue

                    direction = tu.trip.direction_id
                    for stu in tu.stop_time_update:
                        arrival_ts = stu.arrival.time
                        if not arrival_ts or arrival_ts <= now:
                            continue
                        eta_min = round((arrival_ts - now) / 60)
                        if eta_min < 0 or eta_min > 120:
                            continue
                        key = (rid, direction, stu.stop_id)
                        arrivals.setdefault(key, []).append(eta_min)

                if not arrivals:
                    return {}

                # Match each target stop to closest API stop within 500m
                results = {}
                for stop in stops:
                    target_rid = str(stop["route_id"])
                    target_dir = stop["direction_id"]
                    target_lat = stop["lat"]
                    target_lon = stop["lon"]

                    best_etas = []
                    for (rid, direction, api_stop_id), etas in arrivals.items():
                        if rid != target_rid or direction != target_dir:
                            continue

                        # Try exact stop_id match first
                        if api_stop_id == str(stop["stop_id"]):
                            best_etas.extend(etas)
                            continue

                        # Geographic match: check if API stop is within 500m
                        if api_stop_id in stop_coords:
                            slat, slon = stop_coords[api_stop_id]
                            dist = haversine(target_lat, target_lon, slat, slon)
                            if dist < 0.5:
                                best_etas.extend(etas)

                    if best_etas:
                        results[stop["stop_id"]] = sorted(set(best_etas))[:5]

                return results
        except Exception as e:
            logger.error(f"Error in fetch_trip_updates: {type(e).__name__}: {e}")
            return {}


async def fetch_realtime_vehicles(route_ids):
    """Fetch vehicle positions with enriched data for fallback ETA.
    Returns list of vehicle dicts with direction awareness.
    """
    url = f"{API_BASE}/colectivos/vehiclePositions"
    params = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    route_ids_str = {str(r) for r in route_ids}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.error(f"vehiclePositions HTTP {resp.status}")
                    return []

                content = await resp.read()
                feed = gtfs_realtime_pb2.FeedMessage()
                feed.ParseFromString(content)

                seen_ids = set()
                vehicles = []
                for entity in feed.entity:
                    if not entity.HasField("vehicle"):
                        continue
                    v = entity.vehicle
                    v_route_id = str(v.trip.route_id)
                    if v_route_id not in route_ids_str:
                        continue

                    vid = v.vehicle.id
                    if vid in seen_ids:
                        continue
                    seen_ids.add(vid)

                    vehicles.append({
                        "vehicle_id": vid,
                        "route_id": v_route_id,
                        "trip_id": v.trip.trip_id or None,
                        "direction_id": v.trip.direction_id if v.trip.trip_id else None,
                        "latitude": v.position.latitude,
                        "longitude": v.position.longitude,
                        "speed": v.position.speed if v.position.speed else None,
                        "timestamp": v.timestamp,
                    })
                return vehicles
        except Exception as e:
            logger.error(f"Error in fetch_realtime_vehicles: {type(e).__name__}: {e}")
            return []


async def calculate_eta_osrm(bus_lat, bus_lon, stop_lat, stop_lon):
    """Calculate ETA via OSRM routing (third fallback)."""
    url = f"http://router.project-osrm.org/route/v1/driving/{bus_lon},{bus_lat};{stop_lon},{stop_lat}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params={"overview": "false"}, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("routes"):
                        return round(data["routes"][0]["duration"] / 60)
        except Exception:
            pass
    return None


def calculate_eta_speed(dist_km, speed_mps):
    """Calculate ETA from distance and speed (second fallback)."""
    if speed_mps and speed_mps > 0.5:
        speed_kmh = speed_mps * 3.6
        return max(1, round((dist_km / speed_kmh) * 60))
    return None


def calculate_eta_linear(dist_km):
    """Calculate ETA assuming 18 km/h average (last fallback)."""
    return max(1, round((dist_km / 18.0) * 60))


# --- Core ETA Logic ---

async def get_etas_for_stops(stops):
    """Main ETA function. Tries tripUpdates first, then vehiclePositions fallback."""
    route_ids = list({s["route_id"] for s in stops})

    # Primary: tripUpdates (real-time arrival predictions from agency)
    trip_updates = await fetch_trip_updates(route_ids, stops)

    results = {}
    stops_needing_fallback = []

    for stop in stops:
        matching_etas = trip_updates.get(stop["stop_id"])

        if matching_etas:
            results[stop["stop_id"]] = {
                "etas": matching_etas[:3],
                "source": "realtime",
            }
        else:
            stops_needing_fallback.append(stop)

    if not stops_needing_fallback:
        return results

    # Fallback: vehiclePositions
    vehicles = await fetch_realtime_vehicles(route_ids)
    if not vehicles:
        for stop in stops_needing_fallback:
            results[stop["stop_id"]] = {"etas": [], "source": "none"}
        return results

    for stop in stops_needing_fallback:
        # Filter vehicles for this stop's route
        route_vehicles = [v for v in vehicles if v["route_id"] == str(stop["route_id"])]

        # Filter by direction when available
        direction_matched = [v for v in route_vehicles if v["direction_id"] == stop["direction_id"]]
        if direction_matched:
            route_vehicles = direction_matched

        # Calculate distances and filter to nearby (< 10km)
        for v in route_vehicles:
            v["dist"] = haversine(v["latitude"], v["longitude"], stop["lat"], stop["lon"])
        route_vehicles = [v for v in route_vehicles if v["dist"] < 10.0]
        route_vehicles = sorted(route_vehicles, key=lambda x: x["dist"])[:3]

        if not route_vehicles:
            results[stop["stop_id"]] = {"etas": [], "source": "none"}
            continue

        # Calculate ETAs with cascading fallback
        etas = []
        for v in route_vehicles:
            # Try speed-based first
            eta = calculate_eta_speed(v["dist"], v.get("speed"))
            if eta is None:
                # Try OSRM
                eta = await calculate_eta_osrm(v["latitude"], v["longitude"], stop["lat"], stop["lon"])
            if eta is None:
                # Linear fallback
                eta = calculate_eta_linear(v["dist"])
            etas.append(eta)

        etas = sorted(set(etas))
        results[stop["stop_id"]] = {"etas": etas[:3], "source": "estimated"}

    return results


# --- Telegram Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Hola! Soy Bondiero Bot 🚌.\nEnviame el número de línea (ej: /152) o con dirección (ej: /152 rivadavia 4296)."
    )


async def handle_line_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = text.split(maxsplit=1)
    line = parts[0].replace("/", "").strip()
    context.user_data["current_line"] = line

    if len(parts) > 1:
        address = parts[1]
        await update.message.reply_text(f"Buscando '{address}' en CABA...")
        geolocator = Nominatim(user_agent="bondiero_bot_alexis_prod_v2")
        try:
            location = geolocator.geocode(
                f"{address}, Ciudad Autónoma de Buenos Aires, Argentina", timeout=10
            )
            if location:
                return await process_location(update, context, location.latitude, location.longitude)
            else:
                await update.message.reply_text("No encontré esa dirección en CABA. Enviame tu ubicación GPS.")
        except Exception as e:
            if "malformed" in str(e):
                logger.error(f"Critical DB error: {e}")
                await update.message.reply_text("Error en la base de datos del servidor. Reintentando...")
            else:
                logger.error(f"Geocoder error: {e}")
                await update.message.reply_text("Error al buscar dirección. Enviame tu ubicación GPS.")

    await update.message.reply_text(
        f"¿Donde estás? Enviame tu ubicación para buscar las paradas del {line}.",
        reply_markup=ReplyKeyboardMarkup(
            [[{"text": "Enviar Ubicación 📍", "request_location": True}]], one_time_keyboard=True
        ),
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

    eta_data = await get_etas_for_stops(stops)

    response_text = f"🚌 *Línea {line}*\n\n"

    for stop in stops:
        headsign = stop["headsign"].title() if stop["headsign"] else "Destino Desconocido"
        dist_to_stop = haversine(lat, lon, stop["lat"], stop["lon"])
        response_text += f"📍 *Hacia {headsign}*\n"
        response_text += f"Parada: {stop['stop_name']} ({dist_to_stop:.1f} km)\n"

        data = eta_data.get(stop["stop_id"], {"etas": [], "source": "none"})
        etas = data["etas"]
        source = data["source"]

        if not etas:
            response_text += "Sin datos de llegada en este momento.\n\n"
        else:
            proximos = ", ".join([f"{e} min" for e in etas])
            if source == "realtime":
                response_text += f"⏱ Llegan en: *{proximos}*\n\n"
            else:
                response_text += f"📐 Estimado: *{proximos}*\n\n"

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
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_line_command),
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