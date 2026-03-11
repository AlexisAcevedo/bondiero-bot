import asyncio
import aiohttp
import os
from dotenv import load_dotenv
from google.transit import gtfs_realtime_pb2

load_dotenv()
CLIENT_ID = os.getenv("CABA_API_CLIENT_ID")
CLIENT_SECRET = os.getenv("CABA_API_CLIENT_SECRET")

async def test_protobuf():
    url = "https://apitransporte.buenosaires.gob.ar/colectivos/vehiclePositions"
    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    
    print("Descargando GTFS-Realtime (Protobuf)...")
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                print(f"Error HTTP: {resp.status}")
                return
            
            content = await resp.read()
            print(f"Descargados {len(content)} bytes.")
            
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(content)
            
            print(f"Total de vehiculos reportando: {len(feed.entity)}")
            
            # Ver la estructura del primer vehiculo
            if len(feed.entity) > 0:
                entity = feed.entity[0]
                print("\nEjemplo de Vehiculo Protobuf:")
                print(f"Route ID: {entity.vehicle.trip.route_id}")
                print(f"Trip ID: {entity.vehicle.trip.trip_id}")
                print(f"Lat: {entity.vehicle.position.latitude}")
                print(f"Lon: {entity.vehicle.position.longitude}")

if __name__ == "__main__":
    asyncio.run(test_protobuf())
