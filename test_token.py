import os
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("CABA_API_CLIENT_ID")
CLIENT_SECRET = os.getenv("CABA_API_CLIENT_SECRET")

urls = [
    "https://datosabiertos-transporte-apis.buenosaires.gob.ar/token",
    "https://api-transporte.buenosaires.gob.ar/token",
    "https://apitransporte.buenosaires.gob.ar/token",
]

data = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "grant_type": "client_credentials"
}

print(f"Probando credenciales para {CLIENT_ID[:5]}...")

for url in urls:
    try:
        print(f"Probando {url}...", end=" ")
        resp = requests.post(url, data=data, timeout=10)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            print("¡ÉXITO! Token recibido.")
            print(resp.json())
            break
    except Exception as e:
        print(f"Error: {e}")
