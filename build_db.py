import os
import sqlite3
import requests
import zipfile
import csv
import io
from dotenv import load_dotenv
import gc

load_dotenv()

CLIENT_ID = os.getenv("CABA_API_CLIENT_ID")
CLIENT_SECRET = os.getenv("CABA_API_CLIENT_SECRET")
GTFS_URL = "https://apitransporte.buenosaires.gob.ar/colectivos/feed-gtfs"
DB_NAME = "transporte.db"
ZIP_FILE = "gtfs.zip"

def download_gtfs():
    print(f"Descargando GTFS a disco...")
    params = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    headers = {"User-Agent": "Mozilla/5.0"}
    
    with requests.get(GTFS_URL, params=params, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(ZIP_FILE, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    print("Descarga completa.")

def get_csv_reader(zf, filename):
    f = zf.open(filename)
    return csv.DictReader(io.TextIOWrapper(f, encoding='utf-8'))

def build_database():
    if not os.path.exists(ZIP_FILE):
        return

    print(f"Creando base de datos {DB_NAME}...")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = OFF")
    cursor.execute("PRAGMA synchronous = OFF")
    cursor.execute("PRAGMA cache_size = -2000") 

    with zipfile.ZipFile(ZIP_FILE) as zf:
        # 1. Rutas
        print("Procesando routes.txt...")
        cursor.execute("DROP TABLE IF EXISTS routes")
        cursor.execute("CREATE TABLE routes (route_id TEXT, route_short_name TEXT, route_long_name TEXT)")
        
        valid_route_ids = set()
        reader = get_csv_reader(zf, "routes.txt")
        for row in reader:
            if row.get('route_type') == '3' or 'route_type' not in row:
                cursor.execute("INSERT INTO routes VALUES (?, ?, ?)", 
                               (row['route_id'], row['route_short_name'], row.get('route_long_name', '')))
                valid_route_ids.add(row['route_id'])
        
        # 2. Trips: Solo de las rutas válidas y un solo viaje representativo por (route, direction)
        # para que la DB no pese gigas.
        print("Procesando trips.txt (viajes únicos)...")
        cursor.execute("DROP TABLE IF EXISTS trips")
        cursor.execute("CREATE TABLE trips (route_id TEXT, trip_id TEXT, direction_id INTEGER, trip_headsign TEXT)")
        
        valid_trip_ids = set()
        vistos = set() # (route_id, direction_id)
        reader = get_csv_reader(zf, "trips.txt")
        for row in reader:
            rid = row['route_id']
            did = row['direction_id']
            if rid in valid_route_ids and (rid, did) not in vistos:
                cursor.execute("INSERT INTO trips VALUES (?, ?, ?, ?)", 
                               (rid, row['trip_id'], int(did), row.get('trip_headsign', '')))
                valid_trip_ids.add(row['trip_id'])
                vistos.add((rid, did))
        
        del vistos
        gc.collect()

        # 3. Stop Times
        print("Procesando stop_times.txt (Streaming)...")
        cursor.execute("DROP TABLE IF EXISTS stop_times")
        cursor.execute("CREATE TABLE stop_times (trip_id TEXT, stop_id TEXT, stop_sequence INTEGER)")
        
        reader = get_csv_reader(zf, "stop_times.txt")
        batch = []
        for row in reader:
            if row['trip_id'] in valid_trip_ids:
                batch.append((row['trip_id'], row['stop_id'], int(row['stop_sequence'])))
                if len(batch) >= 10000:
                    cursor.executemany("INSERT INTO stop_times VALUES (?, ?, ?)", batch)
                    batch = []
        if batch:
            cursor.executemany("INSERT INTO stop_times VALUES (?, ?, ?)", batch)
        
        del valid_trip_ids
        gc.collect()

        # 4. Stops
        print("Procesando stops.txt...")
        cursor.execute("DROP TABLE IF EXISTS stops")
        cursor.execute("CREATE TABLE stops (stop_id TEXT, stop_name TEXT, stop_lat REAL, stop_lon REAL)")
        
        reader = get_csv_reader(zf, "stops.txt")
        for row in reader:
            cursor.execute("INSERT INTO stops VALUES (?, ?, ?, ?)", 
                           (row['stop_id'], row['stop_name'], float(row['stop_lat']), float(row['stop_lon'])))

    print("Creando índices...")
    cursor.execute("CREATE INDEX idx_routes_name ON routes(route_short_name)")
    cursor.execute("CREATE INDEX idx_stop_times_stop ON stop_times(stop_id)")
    cursor.execute("CREATE INDEX idx_trips_route ON trips(route_id)")
    
    conn.commit()
    conn.close()

    # VACUUM seguro fuera de transaccion
    print("Compactando base de datos (VACUUM)...")
    conn_v = sqlite3.connect(DB_NAME, isolation_level=None)
    conn_v.execute("VACUUM")
    conn_v.close()
    
    if os.path.exists(ZIP_FILE):
        os.remove(ZIP_FILE)
    print("¡Base de datos ultra-optimizada generada!")

if __name__ == "__main__":
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: Credenciales no configuradas.")
    else:
        try:
            download_gtfs()
            build_database()
        except Exception as e:
            print(f"Error: {e}")
