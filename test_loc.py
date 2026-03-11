import sqlite3
import math
from geopy.geocoders import Nominatim

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Radio de la Tierra en km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

print("Geocoding 'rivadavia 4296, Buenos Aires, Argentina'...")
geolocator = Nominatim(user_agent="bondiero_test")
loc = geolocator.geocode("rivadavia 4296, Buenos Aires, Argentina")

if loc:
    user_lat, user_lon = loc.latitude, loc.longitude
    print(f"Ubicación encontrada: {user_lat}, {user_lon} ({loc.address})")
else:
    print("No se encontró la ubicación.")
    exit()

print("\nBuscando paradas de la línea 132...")
conn = sqlite3.connect('transporte.db')
cursor = conn.cursor()

# Buscamos la 132A, 132B, etc.
cursor.execute("SELECT route_id, route_short_name FROM routes WHERE route_short_name LIKE '132%'")
routes = cursor.fetchall()
valid_route_ids = [r[0] for r in routes]

placeholders = ",".join(["?"] * len(valid_route_ids))
query = f"""
SELECT DISTINCT s.stop_id, s.stop_name, s.stop_lat, s.stop_lon
FROM stops s
JOIN stop_times st ON s.stop_id = st.stop_id
JOIN trips t ON st.trip_id = t.trip_id
WHERE t.route_id IN ({placeholders})
"""
cursor.execute(query, valid_route_ids)
stops = cursor.fetchall()
conn.close()

print(f"Total de paradas encontradas para la línea 132: {len(stops)}")

if stops:
    # Mostramos las 5 más cercanas sin filtro de distancia
    stops_with_dist = []
    for s in stops:
        dist = haversine(user_lat, user_lon, s[2], s[3])
        stops_with_dist.append((s, dist))
    
    stops_with_dist.sort(key=lambda x: x[1])
    
    print("\nLas 5 paradas más cercanas a tus coordenadas son:")
    for s, dist in stops_with_dist[:5]:
        print(f"Parada: {s[1]} | Distancia: {dist:.2f} km | Coords: {s[2]}, {s[3]}")
