"""
BioAgent — Módulo de gestión de hábitos con Firebase RTDB.
Permite definir hábitos diarios y registrar si se cumplieron o no cada día.

Estructura en RTDB:
  users/{user_id}/habits/config/{habit_id}/
    name: str
    created_at: int (timestamp)
    
  users/{user_id}/habits/log/{date_iso}/{habit_id}/
    completed: bool
    logged_at: int (timestamp)
"""
import logging
import time
from typing import Optional

from firebase_admin import db
from bioagent.memory import _init_firebase

logger = logging.getLogger(__name__)

def add_habit(user_id: str, name: str) -> Optional[str]:
    """Crea un nuevo hábito para hacerle seguimiento."""
    if not _init_firebase():
        return None
    try:
        ref = db.reference(f"users/{user_id}/habits/config")
        habit_data = {
            "name": name,
            "created_at": int(time.time()),
        }
        result = ref.push(habit_data)
        logger.info(f"✅ Hábito creado: {name} ({result.key})")
        return result.key
    except Exception as e:
        logger.error(f"❌ add_habit error: {e}")
        return None

def remove_habit(user_id: str, habit_id: str) -> bool:
    """Elimina un hábito de la configuración (deja de hacerle seguimiento)."""
    if not _init_firebase():
        return False
    try:
        db.reference(f"users/{user_id}/habits/config/{habit_id}").delete()
        logger.info(f"✅ Hábito eliminado: {habit_id}")
        return True
    except Exception as e:
        logger.error(f"❌ remove_habit error: {e}")
        return False

def get_habits(user_id: str) -> list[dict]:
    """Retorna la lista de hábitos activos configurados por el usuario."""
    if not _init_firebase():
        return []
    try:
        ref = db.reference(f"users/{user_id}/habits/config")
        data = ref.get()
        if not data:
            return []
        
        habits = []
        for habit_id, habit_data in data.items():
            habits.append({
                "id": habit_id,
                "name": habit_data.get("name", "Desconocido")
            })
        return habits
    except Exception as e:
        logger.error(f"❌ get_habits error: {e}")
        return []

def log_habit(user_id: str, habit_id: str, date_iso: str, completed: bool) -> bool:
    """
    Registra si un hábito se cumplió en una fecha específica.
    date_iso: string YYYY-MM-DD
    """
    if not _init_firebase():
        return False
    try:
        ref = db.reference(f"users/{user_id}/habits/log/{date_iso}/{habit_id}")
        ref.set({
            "completed": completed,
            "logged_at": int(time.time())
        })
        logger.info(f"✅ Hábito registrado: {habit_id} en {date_iso} -> {completed}")
        return True
    except Exception as e:
        logger.error(f"❌ log_habit error: {e}")
        return False

def get_habit_logs(user_id: str, date_iso: str) -> dict:
    """
    Retorna el registro de hábitos para una fecha específica.
    Retorna: {habit_id: {"completed": bool, "logged_at": int}}
    """
    if not _init_firebase():
        return {}
    try:
        ref = db.reference(f"users/{user_id}/habits/log/{date_iso}")
        data = ref.get()
        return data if data else {}
    except Exception as e:
        logger.error(f"❌ get_habit_logs error: {e}")
        return {}

def get_habits_summary(user_id: str, date_iso: str) -> str:
    """
    Retorna un texto resumen de los hábitos y su estado en un día, 
    ideal para inyectar en el contexto de Gemini.
    """
    active_habits = get_habits(user_id)
    if not active_habits:
        return "No tienes hábitos configurados actualmente."
        
    logs = get_habit_logs(user_id, date_iso)
    
    lines = [f"## Estado de Hábitos para el {date_iso}:"]
    for h in active_habits:
        h_id = h["id"]
        name = h["name"]
        
        if h_id in logs:
            status = "✅ Completado" if logs[h_id].get("completed") else "❌ No completado"
        else:
            status = "⏳ Sin registrar hoy"
            
        lines.append(f"- {name} (ID: {h_id}): {status}")
        
    return "\n".join(lines)
