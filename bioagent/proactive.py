"""
BioAgent — Motor Proactivo.
Se ejecuta en segundo plano revisando el calendario y las tareas para enviar
mensajes proactivos por WhatsApp (ej. 15 min antes de un evento, check-in nocturno).
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Set

from bioagent.config import OWNER_PHONE_NUMBER
from bioagent import calendar_service, tasks
from bioagent.whatsapp_bot import send_whatsapp_message

logger = logging.getLogger(__name__)

# Memoria temporal para no repetir recordatorios
_notified_events: Set[str] = set()
_night_check_done = False

async def proactive_loop():
    """Bucle infinito que se ejecuta cada 5 minutos."""
    global _night_check_done
    logger.info("⚙️ Motor Proactivo iniciado.")
    
    if not OWNER_PHONE_NUMBER:
        logger.warning("⚠️ No hay OWNER_PHONE_NUMBER. Motor proactivo desactivado.")
        return
        
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            # Aproximación a Lima time (UTC-5)
            now_local = now_utc - timedelta(hours=5)
            
            # 1. Chequear eventos próximos
            events = await calendar_service.get_today_events_async()
            for e in events:
                event_id = e.get("id")
                start_str = e.get("start", "")
                title = e.get("title", "")
                
                if "T" in start_str and event_id not in _notified_events:
                    try:
                        # start_str format: '2026-04-22T10:00:00-05:00'
                        # Parse start time ignoring tz for simple arithmetic if local
                        # Better: use fromisoformat
                        start_time = datetime.fromisoformat(start_str)
                        # ensure start_time is UTC for comparison
                        if start_time.tzinfo:
                            start_time_utc = start_time.astimezone(timezone.utc)
                        else:
                            # assume local
                            start_time_utc = start_time + timedelta(hours=5)
                            start_time_utc = start_time_utc.replace(tzinfo=timezone.utc)
                            
                        diff = start_time_utc - now_utc
                        minutes_diff = diff.total_seconds() / 60.0
                        
                        # Si faltan entre 0 y 20 minutos, enviar aviso
                        if 0 <= minutes_diff <= 20:
                            msg = f"🔔 *Aviso Proactivo:*\nFaltan unos minutos para tu evento: *{title}*."
                            await send_whatsapp_message(OWNER_PHONE_NUMBER, msg)
                            _notified_events.add(event_id)
                    except Exception as e_parse:
                        logger.error(f"Error parseando hora del evento {title}: {e_parse}")

            # 2. Check-in Nocturno (9:00 PM)
            if now_local.hour == 21 and now_local.minute <= 10:
                if not _night_check_done:
                    from bioagent import habits
                    today_str = now_local.strftime("%Y-%m-%d")
                    active_habits = await asyncio.to_thread(habits.get_habits, OWNER_PHONE_NUMBER)
                    pending = await asyncio.to_thread(tasks.get_tasks, OWNER_PHONE_NUMBER, True)
                    
                    msg_parts = ["🌙 *Check-in Nocturno:*"]
                    
                    if active_habits:
                        msg_parts.append("\nEs hora de registrar tus hábitos de hoy. Responde a este mensaje indicando cuáles cumpliste:")
                        for i, h in enumerate(active_habits, 1):
                            msg_parts.append(f"{i}. {h['name']}")
                            
                    if pending:
                        msg_parts.append("\nAdemás, tienes tareas pendientes de hoy. ¿Las aplazamos para mañana o las terminaste?")
                        
                    if not active_habits and not pending:
                        msg_parts.append("\n¡Todo limpio por hoy! Descansa y prepárate para tu rutina de sueño.")
                        
                    msg = "\n".join(msg_parts)
                    await send_whatsapp_message(OWNER_PHONE_NUMBER, msg)
                    _night_check_done = True
            elif now_local.hour < 21:
                # Resetear el check-in nocturno para el próximo día
                _night_check_done = False
                
            # Limpiar memoria de eventos viejos una vez al día (a la medianoche)
            if now_local.hour == 0 and now_local.minute <= 10:
                _notified_events.clear()

        except Exception as e:
            logger.error(f"❌ Error en motor proactivo: {e}")
            
        # Esperar 5 minutos
        await asyncio.sleep(300)
