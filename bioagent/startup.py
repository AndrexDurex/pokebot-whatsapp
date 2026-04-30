"""
BioAgent — Startup: decodifica credenciales desde HF Secrets al arrancar.

En local, los archivos JSON ya existen. En producción (HF Spaces),
las credenciales se guardan como secrets en base64 y se regeneran aquí.
"""
import base64
import json
import logging
import os
from pathlib import Path

from bioagent.config import GOOGLE_CALENDAR_TOKEN_PATH, FIREBASE_CREDENTIALS_PATH

logger = logging.getLogger(__name__)


def _decode_secret_to_file(env_var: str, output_path: str) -> bool:
    """
    Lee una variable de entorno como base64 y la guarda como archivo JSON.
    Retorna True si el archivo fue creado, False si ya existe o no hay secret.
    """
    path = Path(output_path)
    if path.exists():
        return True  # ya existe localmente

    value = os.getenv(env_var, "").strip()
    if not value:
        logger.warning(f"⚠️ Secret '{env_var}' no encontrado.")
        return False

    try:
        # Intentar decodificar como base64
        decoded = base64.b64decode(value).decode("utf-8")
        # Validar que es JSON válido
        json.loads(decoded)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(decoded, encoding="utf-8")
        logger.info(f"✅ Credencial '{output_path}' restaurada desde secret.")
        return True
    except Exception as e:
        logger.error(f"❌ Error decodificando '{env_var}': {e}")
        return False


def prepare_credentials() -> None:
    """
    Prepara todos los archivos de credenciales necesarios.
    En local: no hace nada (ya existen).
    En HF Spaces/Render: los restaura desde los secrets.
    """
    _decode_secret_to_file("FIREBASE_CREDENTIALS_B64", FIREBASE_CREDENTIALS_PATH)
    _decode_secret_to_file("GOOGLE_CALENDAR_TOKEN_B64", GOOGLE_CALENDAR_TOKEN_PATH)
