"""
Script para configurar los índices de Firebase RTDB vía REST API.
Usa el access token del service account para autenticar.
"""
import json
import urllib.request
import subprocess
import sys

# Instalar google-auth si no está
try:
    from google.oauth2 import service_account
    import google.auth.transport.requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "google-auth", "-q"])
    from google.oauth2 import service_account
    import google.auth.transport.requests

# Cargar credenciales del service account
CREDS_PATH = "firebase-credentials.json"
PROJECT_ID = "poketbot-646db"
RTDB_URL = f"https://{PROJECT_ID}-default-rtdb.firebaseio.com"

# Autenticar con el service account
scopes = ["https://www.googleapis.com/auth/firebase.database", 
          "https://www.googleapis.com/auth/userinfo.email"]
creds = service_account.Credentials.from_service_account_file(CREDS_PATH, scopes=scopes)
auth_req = google.auth.transport.requests.Request()
creds.refresh(auth_req)
token = creds.token

# Las reglas con los índices correctos
rules = {
    "rules": {
        ".read": False,
        ".write": False,
        "users": {
            "$user_id": {
                "history": {
                    ".indexOn": ["timestamp"],
                    ".read": False,
                    ".write": False
                },
                "tasks": {
                    ".indexOn": ["created_at"],
                    ".read": False,
                    ".write": False
                }
            }
        }
    }
}

rules_json = json.dumps(rules).encode("utf-8")

# PUT a la API de reglas de RTDB
url = f"{RTDB_URL}/.settings/rules.json?access_token={token}"
req = urllib.request.Request(url, data=rules_json, method="PUT")
req.add_header("Content-Type", "application/json")

try:
    with urllib.request.urlopen(req) as response:
        result = response.read().decode("utf-8")
        print(f"✅ Reglas aplicadas exitosamente!")
        print(f"Respuesta: {result}")
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8")
    print(f"❌ Error HTTP {e.code}: {body}")
except Exception as e:
    print(f"❌ Error: {e}")
