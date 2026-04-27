import logging
from datetime import datetime, timezone
import uuid

from firebase_admin import db
from bioagent.memory import _init_firebase

logger = logging.getLogger(__name__)

def add_reminder(user_id: int, text: str, trigger_iso: str) -> str:
    """Añade un recordatorio a la cola de Firebase."""
    if not _init_firebase():
        return ""
        
    reminder_id = str(uuid.uuid4())[:8]
    try:
        # Convertir trigger_iso a timestamp para fácil comparación
        dt = datetime.fromisoformat(trigger_iso)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
            
        timestamp = dt.timestamp()
        
        ref = db.reference(f"users/{user_id}/reminders/{reminder_id}")
        ref.set({
            "id": reminder_id,
            "text": text,
            "trigger_iso": trigger_iso,
            "timestamp": timestamp,
            "sent": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        logger.info(f"⏰ Recordatorio añadido: {text} para {trigger_iso}")
        return reminder_id
    except Exception as e:
        logger.error(f"❌ add_reminder error: {e}")
        return ""

def get_pending_reminders(user_id: int) -> list[dict]:
    """Obtiene los recordatorios cuya hora ya pasó y no han sido enviados."""
    if not _init_firebase():
        return []
        
    try:
        ref = db.reference(f"users/{user_id}/reminders")
        all_reminders = ref.get()
        if not all_reminders:
            return []
            
        now_ts = datetime.now(timezone.utc).timestamp()
        pending = []
        
        for r_id, r_data in all_reminders.items():
            if not r_data.get("sent", True):
                trigger_ts = r_data.get("timestamp", 0)
                if trigger_ts <= now_ts:
                    pending.append(r_data)
                    
        return pending
    except Exception as e:
        logger.error(f"❌ get_pending_reminders error: {e}")
        return []

def mark_reminder_sent(user_id: int, reminder_id: str) -> bool:
    """Marca un recordatorio como enviado y/o lo elimina."""
    if not _init_firebase():
        return False
        
    try:
        # Por limpieza, mejor lo borramos una vez enviado
        ref = db.reference(f"users/{user_id}/reminders/{reminder_id}")
        ref.delete()
        logger.info(f"✅ Recordatorio {reminder_id} ejecutado y eliminado.")
        return True
    except Exception as e:
        logger.error(f"❌ mark_reminder_sent error: {e}")
        return False
