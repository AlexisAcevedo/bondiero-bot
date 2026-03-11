import os
import sqlite3
import requests
import zipfile
import io
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("CABA_API_CLIENT_ID")
CLIENT_SECRET = os.getenv("CABA_API_CLIENT_SECRET")
# URL Base actualizada 2024/2025
GTFS_URL = "https://apitransporte.buenosaires.gob.ar/colectivos/feed-gtfs"
DB_NAME = "transporte.db"

def download_gtfs():
    print(f"Descargando GTFS desde {GTFS_URL}...")
    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/zip"
    }
    
    try:
        # En la version actual, pasamos client_id y client_secret directos como params
        response = requests.get(GTFS_URL, params=params, headers=headers, timeout=120)
        response.raise_for_status()
        
        # Validacion de ZIP
        if not response.content.startswith(b'PK'):
            print("ERROR: El servidor no devolvió un archivo ZIP válido.")
            print("Contenido recibido (primeros 100 caracteres):")
            print(response.content[:100].decode('utf-8', errors='ignore'))
            raise Exception("Contenido inválido (posible error de API o credenciales).")

        print("Descarga completada, procesando archivo ZIP...")
        return zipfile.ZipFile(io.BytesIO(response.content))
        
    except Exception as e:
        raise Exception(f"Error fatal en la descarga: {e}")

def build_database(zf):
    print(f"Creando base de datos {DB_NAME}...")
    conn = sqlite3.connect(DB_NAME)
    
    # 1. Rutas: Solo colectivos (route_type 3)
    print("Procesando routes.txt...")
    routes_df = pd.read_csv(zf.open("routes.txt"))
    # En CABA, route_type 3 es Colectivo. Filtramos para ahorrar espacio.
    if 'route_type' in routes_df.columns:
        routes_df = routes_df[routes_df['route_type'] == 3]
    routes_df = routes_df[['route_id', 'route_short_name', 'route_long_name']]
    routes_df.to_sql("routes", conn, if_exists="replace", index=False)
    valid_route_ids = routes_df['route_id'].unique()

    # 2. Trips: Solo los que pertenecen a las rutas de colectivos
    print("Procesando trips.txt...")
    trips_df = pd.read_csv(zf.open("trips.txt"))
    trips_df = trips_df[trips_df['route_id'].isin(valid_route_ids)]
    trips_df = trips_df[['route_id', 'trip_id', 'direction_id', 'trip_headsign']]
    trips_df.to_sql("trips", conn, if_exists="replace", index=False)
    valid_trip_ids = trips_df['trip_id'].unique()

    # 3. Stop Times (LA TABLA MÁS PESADA): Solo columnas esenciales
    # No necesitamos arrival_time ni departure_time para tiempo real/OSRM
    print("Procesando stop_times.txt (esto puede tardar)...")
    # Usamos chunksize para no agotar la RAM en Fly.io
    stop_times_iter = pd.read_csv(zf.open("stop_times.txt"), chunksize=100000)
    first_chunk = True
    for chunk in stop_times_iter:
        # Filtrar solo trips de colectivos y columnas minimas
        chunk = chunk[chunk['trip_id'].isin(valid_trip_ids)]
        chunk = chunk[['trip_id', 'stop_id', 'stop_sequence']]
        chunk.to_sql("stop_times", conn, if_exists="replace" if first_chunk else "append", index=False)
        first_chunk = False

    # 4. Stops: Solo las paradas que realmente se usan en los trips filtrados
    print("Procesando stops.txt...")
    stops_df = pd.read_csv(zf.open("stops.txt"))
    stops_df = stops_df[['stop_id', 'stop_name', 'stop_lat', 'stop_lon']]
    stops_df.to_sql("stops", conn, if_exists="replace", index=False)

    # Crear indices para velocidad
    print("Creando índices...")
    cursor = conn.cursor()
    cursor.execute("CREATE INDEX idx_routes_name ON routes(route_short_name)")
    cursor.execute("CREATE INDEX idx_stop_times_trip ON stop_times(trip_id)")
    cursor.execute("CREATE INDEX idx_stop_times_stop ON stop_times(stop_id)")
    cursor.execute("CREATE INDEX idx_trips_route ON trips(route_id)")
    
    # COMPRESIÓN FINAL
    print("Compactando base de datos (VACUUM)...")
    conn.execute("VACUUM")
    
    conn.commit()
    conn.close()
    print("¡Base de datos optimizada generada con éxito!")

if __name__ == "__main__":
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: CABA_API_CLIENT_ID o CLIENT_SECRET no configurados en .env")
    else:
        try:
            zip_file = download_gtfs()
            build_database(zip_file)
        except Exception as e:
            print(f"Error fatal: {e}")
