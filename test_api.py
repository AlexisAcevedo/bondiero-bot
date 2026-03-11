import asyncio
import aiohttp
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()
CLIENT_ID = os.getenv("CABA_API_CLIENT_ID")
CLIENT_SECRET = os.getenv("CABA_API_CLIENT_SECRET")

async def test_api():
    conn = sqlite3.connect('transporte.db')
    cursor = conn.cursor()
    
    # Obtener algunos route_ids para las lineas 8 y 132
    cursor.execute("SELECT route_id, route_short_name FROM routes WHERE route_short_name LIKE '8%' OR route_short_name LIKE '132%' LIMIT 10")
    routes = cursor.fetchall()
    conn.close()
    
    route_ids = [r[0] for r in routes]
    print(f"Buscando en API para los route_ids: {route_ids}")

    url = "https://apitransporte.buenosaires.gob.ar/colectivos/vehiclePositionsSimple"
    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "json": 1
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                print(f"Error HTTP {resp.status}")
                return
            
            data = await resp.json()
            print(f"Total de vehiculos reportando en TODA la ciudad: {len(data)}")
            
            if len(data) > 0:
                print("Ejemplo de un vehiculo:", data[0])
            
            # Ver cuantos coinciden con nuestros route_ids
            matching = [v for v in data if str(v.get('route_id')) in route_ids]
            print(f"Vehiculos encontrados para las lineas 8 y 132: {len(matching)}")
            
            # Imprimir los route_ids que si estan reportando (primeros 10 unicos)
            active_routes = list(set([str(v.get('route_id')) for v in data]))[:10]
            print(f"Algunos route_ids activos en la API: {active_routes}")

if __name__ == "__main__":
    asyncio.run(test_api())
