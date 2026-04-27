"""
BioAgent — Módulo de Google Calendar.
Lee/crea/modifica eventos del calendario del usuario.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from bioagent.config import GOOGLE_CREDENTIALS_PATH, GOOGLE_CALENDAR_TOKEN_PATH, CALENDAR_ID

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_service = None


def _get_service():
    """Retorna (o inicializa) el cliente de Calendar API."""
    global _service
    if _service:
        return _service

    try:
        creds = Credentials.from_authorized_user_file(GOOGLE_CALENDAR_TOKEN_PATH, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Guardar token renovado
            with open(GOOGLE_CALENDAR_TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        _service = build("calendar", "v3", credentials=creds)
        logger.info("✅ Google Calendar conectado.")
        return _service
    except Exception as e:
        logger.error(f"❌ Calendar init error: {e}")
        return None


# ── Lectura de eventos ─────────────────────────────────────────────────────────

from bioagent.config import GOOGLE_CREDENTIALS_PATH, GOOGLE_CALENDAR_TOKEN_PATH, CALENDAR_ID, CALENDAR_ID_ROUTINES

def get_upcoming_events(days: int = 7, max_results: int = 10) -> list[dict]:
    """
    Retorna los próximos eventos combinados de ambos calendarios (Principal y Rutinas).
    Cada evento: {'id', 'title', 'start', 'end', 'description', 'calendar_type'}
    """
    service = _get_service()
    if not service:
        return []

    try:
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days)
        events = []

        for cal_id, cal_type in [(CALENDAR_ID, "main"), (CALENDAR_ID_ROUTINES, "routine")]:
            if not cal_id or cal_id == "primary" and cal_type == "routine":
                continue # Skip if routines not configured
            try:
                result = service.events().list(
                    calendarId=cal_id,
                    timeMin=now.isoformat(),
                    timeMax=time_max.isoformat(),
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()

                for e in result.get("items", []):
                    start = e["start"].get("dateTime", e["start"].get("date", ""))
                    end = e["end"].get("dateTime", e["end"].get("date", ""))
                    events.append({
                        "id": e.get("id"),
                        "title": e.get("summary", "Sin título"),
                        "start": start,
                        "end": end,
                        "description": e.get("description", ""),
                        "color_id": e.get("colorId", ""),
                        "calendar_type": cal_type
                    })
            except Exception as inner_e:
                logger.warning(f"No se pudo leer el calendario {cal_type}: {inner_e}")
                
        # Sort combined events by start time
        events.sort(key=lambda x: x["start"])
        return events[:max_results]
    except Exception as e:
        logger.error(f"❌ get_upcoming_events error: {e}")
        return []

def get_today_events() -> list[dict]:
    """Retorna los eventos de hoy."""
    return get_upcoming_events(days=1)


# ── Creación de eventos ────────────────────────────────────────────────────────

def create_event(
    title: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    color_id: Optional[str] = None,
    recurrence: Optional[str] = None,
    calendar_type: str = "main",
) -> Optional[dict]:
    """
    Crea un evento en el calendario indicado.
    calendar_type: 'main' o 'routine'
    """
    service = _get_service()
    if not service:
        return None

    event_body = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": "America/Lima"},
        "end": {"dateTime": end_iso, "timeZone": "America/Lima"},
    }
    if color_id:
        event_body["colorId"] = color_id
    if recurrence:
        event_body["recurrence"] = [recurrence]

    target_cal = CALENDAR_ID_ROUTINES if calendar_type == "routine" else CALENDAR_ID

    try:
        created = service.events().insert(
            calendarId=target_cal, body=event_body
        ).execute()
        logger.info(f"✅ Evento creado en {calendar_type}: {title} ({start_iso})")
        return created
    except Exception as e:
        logger.error(f"❌ create_event error: {e}")
        return None


def delete_event(event_id: str) -> bool:
    """Elimina un evento del calendario por ID (busca en ambos calendarios)."""
    service = _get_service()
    if not service:
        return False
    try:
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        logger.info(f"✅ Evento eliminado (main): {event_id}")
        return True
    except Exception:
        try:
            service.events().delete(calendarId=CALENDAR_ID_ROUTINES, eventId=event_id).execute()
            logger.info(f"✅ Evento eliminado (routine): {event_id}")
            return True
        except Exception as e2:
            logger.error(f"❌ delete_event error en ambos: {e2}")
            return False


def update_event(
    event_id: str,
    title: Optional[str] = None,
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
    description: Optional[str] = None,
    color_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Modifica un evento existente en el calendario (busca en ambos).
    """
    service = _get_service()
    if not service:
        return None
        
    def _try_update(cal_id: str):
        existing = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        if title: existing["summary"] = title
        if description is not None: existing["description"] = description
        if start_iso: existing["start"] = {"dateTime": start_iso, "timeZone": "America/Lima"}
        if end_iso: existing["end"] = {"dateTime": end_iso, "timeZone": "America/Lima"}
        if color_id: existing["colorId"] = color_id
        
        updated = service.events().update(
            calendarId=cal_id, eventId=event_id, body=existing
        ).execute()
        return updated

    try:
        updated = _try_update(CALENDAR_ID)
        logger.info(f"✅ Evento actualizado (main): {event_id}")
        return updated
    except Exception:
        try:
            updated = _try_update(CALENDAR_ID_ROUTINES)
            logger.info(f"✅ Evento actualizado (routine): {event_id}")
            return updated
        except Exception as e2:
            logger.error(f"❌ update_event error en ambos: {e2}")
            return None


# ── Resumen para el agente ─────────────────────────────────────────────────────

def get_agenda_summary(days: int = 7) -> str:
    """
    Retorna un texto con el resumen de la agenda para inyectar al prompt.
    Separa las rutinas fijas (color Banana/5) de los eventos regulares.
    Incluye el ID del evento para que Gemini pueda modificarlo o borrarlo.
    """
    events = get_upcoming_events(days=days)
    if not events:
        return f"📅 No hay eventos en los próximos {days} días."

    # Separar rutinas del resto basándose en el calendar_type
    routines = [e for e in events if e.get("calendar_type") == "routine"]
    agenda = [e for e in events if e.get("calendar_type") != "routine"]

    def format_event(e):
        start = e["start"].replace("T", " ").split("+")[0][:16]
        end = e["end"].replace("T", " ").split("+")[0][11:16] if "T" in e["end"] else ""
        event_id = e.get("id", "sin-id")
        time_str = f"{start} → {end}" if end else start
        line = f"• {time_str} — {e['title']} (ID: {event_id})"
        if e["description"]:
            line += f"\n  _{e['description'][:80]}_"
        return line

    lines = []
    
    if agenda:
        lines.append(f"📅 *Agenda próximos {days} días:*")
        lines.extend(format_event(e) for e in agenda)
    
    if routines:
        if lines:
            lines.append("")
        lines.append("🔄 *Rutinas fijas:*")
        lines.extend(format_event(e) for e in routines)

    return "\n".join(lines) if lines else f"📅 No hay eventos en los próximos {days} días."


# ── Async wrappers ─────────────────────────────────────────────────────────────

async def get_agenda_summary_async(days: int = 7) -> str:
    return await asyncio.to_thread(get_agenda_summary, days)

async def create_event_async(title, start_iso, end_iso, description="", color_id=None, recurrence=None, calendar_type="main"):
    return await asyncio.to_thread(create_event, title, start_iso, end_iso, description, color_id, recurrence, calendar_type)

async def update_event_async(event_id, title=None, start_iso=None, end_iso=None, description=None, color_id=None):
    return await asyncio.to_thread(update_event, event_id, title, start_iso, end_iso, description, color_id)

async def get_today_events_async() -> list[dict]:
    return await asyncio.to_thread(get_today_events)
