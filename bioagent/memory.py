"""
BioAgent — Memoria de largo plazo con Firebase Realtime Database.
Guarda/recupera historial de conversaciones y perfil del usuario.

Estructura en RTDB:
  users/{user_id}/
    profile/         → datos del usuario (horarios, preferencias, etc.)
    history/         → últimas N interacciones ordenadas por timestamp
"""
import logging
import time
from typing import Optional

import firebase_admin
from firebase_admin import credentials, db

from bioagent.config import (
    FIREBASE_CREDENTIALS_PATH,
    FIREBASE_RTDB_URL,
    FIREBASE_PROJECT_ID,
)

logger = logging.getLogger(__name__)

_initialized = False
MAX_HISTORY = 20   # máximo de turnos a conservar en RTDB


def _init_firebase() -> bool:
    """Inicializa Firebase Admin SDK (singleton)."""
    global _initialized
    if _initialized:
        return True
    if not FIREBASE_CREDENTIALS_PATH or not FIREBASE_RTDB_URL:
        logger.warning("⚠️ Firebase: credenciales no configuradas.")
        return False
    try:
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_RTDB_URL})
        _initialized = True
        logger.info(f"✅ Firebase conectado: {FIREBASE_PROJECT_ID}")
        return True
    except Exception as e:
        logger.error(f"❌ Firebase init error: {e}")
        return False


# ── Perfil del usuario ─────────────────────────────────────────────────────────

def save_profile(user_id: int, data: dict) -> bool:
    """Guarda/actualiza el perfil del usuario en RTDB."""
    if not _init_firebase():
        return False
    try:
        ref = db.reference(f"users/{user_id}/profile")
        ref.update(data)
        return True
    except Exception as e:
        logger.error(f"❌ save_profile error: {e}")
        return False


def get_profile(user_id: int) -> dict:
    """Recupera el perfil del usuario. Retorna dict vacío si no existe."""
    if not _init_firebase():
        return {}
    try:
        ref = db.reference(f"users/{user_id}/profile")
        return ref.get() or {}
    except Exception as e:
        logger.error(f"❌ get_profile error: {e}")
        return {}


# ── Historial de conversación ──────────────────────────────────────────────────

def save_message(user_id: int, role: str, text: str) -> bool:
    """
    Guarda un mensaje en el historial del usuario.
    role: 'user' | 'model'
    """
    if not _init_firebase():
        return False
    try:
        ref = db.reference(f"users/{user_id}/history")
        ref.push({
            "role": role,
            "text": text,
            "timestamp": int(time.time()),
        })
        # Mantener solo los últimos MAX_HISTORY mensajes
        _trim_history(user_id)
        return True
    except Exception as e:
        logger.error(f"❌ save_message error: {e}")
        return False


def get_recent_history(user_id: int, n: int = 10) -> list[dict]:
    """
    Recupera los últimos N mensajes del historial.
    Retorna lista de {'role': str, 'text': str, 'timestamp': int}
    """
    if not _init_firebase():
        return []
    try:
        ref = db.reference(f"users/{user_id}/history")
        data = ref.order_by_child("timestamp").limit_to_last(n).get()
        if not data:
            return []
        msgs = list(data.values())
        msgs.sort(key=lambda x: x.get("timestamp", 0))
        return msgs
    except Exception as e:
        logger.error(f"❌ get_recent_history error: {e}")
        return []


def build_gemini_history(user_id: int, n: int = 8) -> list[dict]:
    """
    Convierte el historial de RTDB al formato que espera Gemini:
    [{'role': 'user'|'model', 'parts': [{'text': '...'}]}, ...]
    """
    msgs = get_recent_history(user_id, n)
    return [
        {"role": m["role"], "parts": [{"text": m["text"]}]}
        for m in msgs
        if m.get("role") in ("user", "model") and m.get("text")
    ]

def build_openrouter_history(user_id: int, n: int = 10) -> list[dict]:
    """
    Convierte el historial de RTDB al formato OpenAI (OpenRouter):
    [{'role': 'user'|'assistant', 'content': '...'}, ...]
    """
    msgs = get_recent_history(user_id, n)
    history = []
    for m in msgs:
        role = m["role"]
        # Convertir 'model' (Gemini) a 'assistant' (OpenAI)
        if role == "model":
            role = "assistant"
        
        if role in ("user", "assistant") and m.get("text"):
            history.append({"role": role, "content": m["text"]})
    return history


def _trim_history(user_id: int) -> None:
    """Elimina mensajes más antiguos si se supera MAX_HISTORY."""
    try:
        ref = db.reference(f"users/{user_id}/history")
        data = ref.order_by_child("timestamp").get()
        if data and len(data) > MAX_HISTORY:
            keys = list(data.keys())
            to_delete = keys[: len(keys) - MAX_HISTORY]
            for key in to_delete:
                ref.child(key).delete()
    except Exception as e:
        logger.error(f"❌ _trim_history error: {e}")
