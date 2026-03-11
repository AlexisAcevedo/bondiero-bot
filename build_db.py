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
    
    # Procesar archivos necesarios del GTFS
    files_to_process = ["routes.txt", "stops.txt", "trips.txt", "stop_times.txt"]
    for file_name in files_to_process:
        print(f"Procesando {file_name}...")
        df = pd.read_csv(zf.open(file_name))
        
        # Limpieza basica segun el archivo
        if file_name == "routes.txt":
            df = df[['route_id', 'route_short_name', 'route_long_name']]
        elif file_name == "stops.txt":
            df = df[['stop_id', 'stop_name', 'stop_lat', 'stop_lon']]
        elif file_name == "trips.txt":
            df = df[['route_id', 'trip_id', 'direction_id', 'trip_headsign']]
        elif file_name == "stop_times.txt":
            df = df[['trip_id', 'stop_id', 'stop_sequence']]
        
        table_name = file_name.replace(".txt", "")
        df.to_sql(table_name, conn, if_exists="replace", index=False)

    # Crear indices para velocidad
    print("Creando índices...")
    cursor = conn.cursor()
    cursor.execute("CREATE INDEX idx_routes_name ON routes(route_short_name)")
    cursor.execute("CREATE INDEX idx_stop_times_trip ON stop_times(trip_id)")
    cursor.execute("CREATE INDEX idx_stop_times_stop ON stop_times(stop_id)")
    cursor.execute("CREATE INDEX idx_trips_route ON trips(route_id)")
    
    conn.commit()
    conn.close()
    print("¡Base de datos generada con éxito!")

if __name__ == "__main__":
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: CABA_API_CLIENT_ID o CLIENT_SECRET no configurados en .env")
    else:
        try:
            zip_file = download_gtfs()
            build_database(zip_file)
        except Exception as e:
            print(f"Error fatal: {e}")
