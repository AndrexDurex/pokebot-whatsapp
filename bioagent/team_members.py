"""
BioAgent — Registro y gestión de miembros del equipo.
Almacena los datos de cada miembro en Firebase RTDB.

Estructura en RTDB:
  team_members/{phone_number}/
    name: str
    role: "admin" | "member"
    onboarded: bool
    joined_at: int (timestamp)
"""
import logging
import time
from typing import Optional

from firebase_admin import db

from bioagent.memory import _init_firebase

logger = logging.getLogger(__name__)

# Miembros autorizados (pre-registrados)
# Se cargan desde config al inicializar
AUTHORIZED_MEMBERS = {
    "51931048021": {"name": "André", "role": "admin"},
    "51975404354": {"name": "Joaquín", "role": "member"},
    "51997875950": {"name": "Michelle", "role": "member"},
    "51980436235": {"name": "Daniela", "role": "member"},
}


def is_authorized(phone_number: str) -> bool:
    """Verifica si un número está autorizado para usar el bot."""
    # Normalizar: quitar '+' y espacios
    clean = phone_number.replace("+", "").replace(" ", "")
    return clean in AUTHORIZED_MEMBERS


def get_member_name(phone_number: str) -> str:
    """Retorna el nombre del miembro o 'Desconocido'."""
    clean = phone_number.replace("+", "").replace(" ", "")
    member = AUTHORIZED_MEMBERS.get(clean)
    return member["name"] if member else "Desconocido"


def get_member_role(phone_number: str) -> str:
    """Retorna el rol del miembro: 'admin', 'member' o 'unauthorized'."""
    clean = phone_number.replace("+", "").replace(" ", "")
    member = AUTHORIZED_MEMBERS.get(clean)
    return member["role"] if member else "unauthorized"


def is_admin(phone_number: str) -> bool:
    """Verifica si un miembro es administrador."""
    return get_member_role(phone_number) == "admin"


def get_all_members() -> dict:
    """Retorna todos los miembros autorizados."""
    return AUTHORIZED_MEMBERS.copy()


def get_all_member_numbers() -> list[str]:
    """Retorna los números de todos los miembros."""
    return list(AUTHORIZED_MEMBERS.keys())


# ── Firebase: Estado de onboarding ──────────────────────────────────────────────

def is_onboarded(phone_number: str) -> bool:
    """Verifica si un usuario ya pasó por el onboarding tutorial."""
    if not _init_firebase():
        return True  # Si Firebase falla, asumimos que ya hizo onboarding
    try:
        clean = phone_number.replace("+", "").replace(" ", "")
        ref = db.reference(f"team_members/{clean}/onboarded")
        result = ref.get()
        return result is True
    except Exception as e:
        logger.error(f"❌ is_onboarded error: {e}")
        return True


def mark_onboarded(phone_number: str) -> bool:
    """Marca a un usuario como onboarded."""
    if not _init_firebase():
        return False
    try:
        clean = phone_number.replace("+", "").replace(" ", "")
        member = AUTHORIZED_MEMBERS.get(clean, {})
        ref = db.reference(f"team_members/{clean}")
        ref.update({
            "name": member.get("name", "Desconocido"),
            "role": member.get("role", "member"),
            "onboarded": True,
            "joined_at": int(time.time()),
        })
        logger.info(f"✅ Miembro onboarded: {clean} ({member.get('name', '?')})")
        return True
    except Exception as e:
        logger.error(f"❌ mark_onboarded error: {e}")
        return False


def get_member_display(phone_number: str) -> str:
    """Retorna 'Nombre (rol)' para logs y mensajes."""
    name = get_member_name(phone_number)
    role = get_member_role(phone_number)
    return f"{name} ({role})"
