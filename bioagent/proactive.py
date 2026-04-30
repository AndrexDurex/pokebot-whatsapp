"""
BioAgent — Motor Proactivo Unificado (Multi-usuario).
Se ejecuta en segundo plano cada 5 minutos.
Para cada usuario registrado:
  - Envía recordatorios de eventos próximos (15 min antes)
  - Envía briefing matutino (8:00 AM)
  - Envía check-in nocturno (9:00 PM)
  - Ejecuta recordatorios dinámicos de Firebase
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Set

from bioagent import calendar_service, tasks, team_members, reminders, briefing
from bioagent.whatsapp_bot import send_whatsapp_message

logger = logging.getLogger(__name__)

# Memoria temporal para no repetir notificaciones
_notified_events: Set[str] = set()    # event_id:user_phone
_briefing_sent: Set[str] = set()       # "YYYY-MM-DD:user_phone"
_night_check_sent: Set[str] = set()    # "YYYY-MM-DD:user_phone"


async def proactive_loop():
    """Bucle infinito que se ejecuta cada 5 minutos para TODOS los usuarios."""
    logger.info("⚙️ Motor Proactivo Unificado iniciado (4 usuarios).")

    # Esperar 30 segundos al inicio para que Firebase y Calendar se inicialicen
    await asyncio.sleep(30)

    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc - timedelta(hours=5)  # Lima = UTC-5

            # Iterar sobre TODOS los miembros del equipo
            for user_phone in team_members.get_all_member_numbers():
                try:
                    await _process_user_proactive(user_phone, now_utc, now_local)
                except Exception as user_e:
                    member_name = team_members.get_member_name(user_phone)
                    logger.error(f"❌ Error proactivo para {member_name}: {user_e}")

            # Limpiar memoria de eventos viejos una vez al día (a la medianoche)
            if now_local.hour == 0 and now_local.minute <= 10:
                _notified_events.clear()
                _briefing_sent.clear()
                _night_check_sent.clear()

        except Exception as e:
            logger.error(f"❌ Error en motor proactivo: {e}")

        # Esperar 5 minutos
        await asyncio.sleep(300)


async def _process_user_proactive(
    user_phone: str,
    now_utc: datetime,
    now_local: datetime,
) -> None:
    """Procesa todas las acciones proactivas para un usuario."""

    # ── 1. Recordatorios de eventos próximos (15 min antes) ────────────────
    try:
        events = await asyncio.to_thread(
            calendar_service.get_user_upcoming_events, user_phone, days=1
        )
        for e in events:
            event_id = e.get("id", "")
            start_str = e.get("start", "")
            title = e.get("title", "")
            notif_key = f"{event_id}:{user_phone}"

            if "T" in start_str and notif_key not in _notified_events:
                try:
                    start_time = datetime.fromisoformat(start_str)
                    if start_time.tzinfo:
                        start_time_utc = start_time.astimezone(timezone.utc)
                    else:
                        start_time_utc = (start_time + timedelta(hours=5)).replace(
                            tzinfo=timezone.utc
                        )

                    diff_minutes = (start_time_utc - now_utc).total_seconds() / 60.0

                    if 0 <= diff_minutes <= 20:
                        msg = f"🔔 *Aviso:* Faltan unos minutos para *{title}*."
                        await send_whatsapp_message(user_phone, msg)
                        _notified_events.add(notif_key)
                except Exception as e_parse:
                    logger.error(f"Error parseando evento {title}: {e_parse}")
    except Exception as e:
        logger.warning(f"⚠️ No se pudieron chequear eventos de {user_phone}: {e}")

    # ── 2. Briefing Matutino (8:00 AM) ─────────────────────────────────────
    today_key = f"{now_local.strftime('%Y-%m-%d')}:{user_phone}"
    if now_local.hour == 8 and now_local.minute <= 10:
        if today_key not in _briefing_sent:
            try:
                briefing_msg = await briefing.generate_briefing(user_phone)
                await send_whatsapp_message(user_phone, briefing_msg)
                _briefing_sent.add(today_key)
                member_name = team_members.get_member_name(user_phone)
                logger.info(f"🌅 Briefing enviado a {member_name}")
            except Exception as e:
                logger.error(f"❌ Error briefing para {user_phone}: {e}")

    # ── 3. Check-in Nocturno (9:00 PM) ────────────────────────────────────
    night_key = f"night:{now_local.strftime('%Y-%m-%d')}:{user_phone}"
    if now_local.hour == 21 and now_local.minute <= 10:
        if night_key not in _night_check_sent:
            try:
                checkin_msg = await briefing.generate_night_checkin(user_phone)
                await send_whatsapp_message(user_phone, checkin_msg)
                _night_check_sent.add(night_key)
                member_name = team_members.get_member_name(user_phone)
                logger.info(f"🌙 Check-in nocturno enviado a {member_name}")
            except Exception as e:
                logger.error(f"❌ Error check-in para {user_phone}: {e}")

    # ── 4. Recordatorios Dinámicos (Firebase) ──────────────────────────────
    try:
        pending_rems = await asyncio.to_thread(
            reminders.get_pending_reminders, user_phone
        )
        for r in pending_rems:
            text = r.get("text", "")
            r_id = r.get("id", "")
            if text and r_id:
                msg = f"⏰ *Recordatorio:* {text}"
                await send_whatsapp_message(user_phone, msg)
                await asyncio.to_thread(
                    reminders.mark_reminder_sent, user_phone, r_id
                )
    except Exception as e:
        logger.warning(f"⚠️ Error recordatorios de {user_phone}: {e}")
