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

def get_upcoming_events(days: int = 7, max_results: int = 10) -> list[dict]:
    """
    Retorna los próximos eventos del calendario.
    Cada evento: {'id', 'title', 'start', 'end', 'description'}
    """
    service = _get_service()
    if not service:
        return []

    try:
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days)

        result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = []
        for e in result.get("items", []):
            start = e["start"].get("dateTime", e["start"].get("date", ""))
            end = e["end"].get("dateTime", e["end"].get("date", ""))
            events.append({
                "id": e.get("id"),
                "title": e.get("summary", "Sin título"),
                "start": start,
                "end": end,
                "description": e.get("description", ""),
            })
        return events
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
) -> Optional[dict]:
    """
    Crea un evento en el calendario.
    color_id: '1'=Lavanda, '2'=Salvia, '4'=Flamingo(rosa), '5'=Banana,
              '6'=Mandarina, '7'=Pavo real, '9'=Arándano, '11'=Tomate
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

    try:
        created = service.events().insert(
            calendarId=CALENDAR_ID, body=event_body
        ).execute()
        logger.info(f"✅ Evento creado: {title} ({start_iso})")
        return created
    except Exception as e:
        logger.error(f"❌ create_event error: {e}")
        return None


def delete_event(event_id: str) -> bool:
    """Elimina un evento del calendario por ID."""
    service = _get_service()
    if not service:
        return False
    try:
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        logger.info(f"✅ Evento eliminado: {event_id}")
        return True
    except Exception as e:
        logger.error(f"❌ delete_event error: {e}")
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
    Modifica un evento existente en el calendario. Solo actualiza los campos que se pasen.
    Ideal para reprogramar horarios, cambiar títulos o añadir descripciones.
    """
    service = _get_service()
    if not service:
        return None
    try:
        # Obtener el evento actual para hacer patch (no sobrescribir todo)
        existing = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
        
        if title:
            existing["summary"] = title
        if description is not None:
            existing["description"] = description
        if start_iso:
            existing["start"] = {"dateTime": start_iso, "timeZone": "America/Lima"}
        if end_iso:
            existing["end"] = {"dateTime": end_iso, "timeZone": "America/Lima"}
        if color_id:
            existing["colorId"] = color_id

        updated = service.events().update(
            calendarId=CALENDAR_ID, eventId=event_id, body=existing
        ).execute()
        logger.info(f"✅ Evento actualizado: {event_id}")
        return updated
    except Exception as e:
        logger.error(f"❌ update_event error: {e}")
        return None


# ── Resumen para el agente ─────────────────────────────────────────────────────

def get_agenda_summary(days: int = 7) -> str:
    """
    Retorna un texto con el resumen de la agenda para inyectar al prompt.
    Incluye el ID del evento para que Gemini pueda modificarlo o borrarlo.
    """
    events = get_upcoming_events(days=days)
    if not events:
        return f"📅 No hay eventos en los próximos {days} días."

    lines = [f"📅 **Agenda próximos {days} días:**\n"]
    for e in events:
        start = e["start"].replace("T", " ").split("+")[0][:16]
        end = e["end"].replace("T", " ").split("+")[0][11:16] if "T" in e["end"] else ""
        event_id = e.get("id", "sin-id")
        
        time_str = f"{start} a {end}" if end else start
        lines.append(f"• {time_str} — {e['title']} (ID: {event_id})")
        if e["description"]:
            lines.append(f"  _{e['description'][:80]}_")

    return "\n".join(lines)


# ── Async wrappers ─────────────────────────────────────────────────────────────

async def get_agenda_summary_async(days: int = 7) -> str:
    return await asyncio.to_thread(get_agenda_summary, days)

async def create_event_async(title, start_iso, end_iso, description="", color_id=None):
    return await asyncio.to_thread(create_event, title, start_iso, end_iso, description, color_id)

async def update_event_async(event_id, title=None, start_iso=None, end_iso=None, description=None, color_id=None):
    return await asyncio.to_thread(update_event, event_id, title, start_iso, end_iso, description, color_id)

async def get_today_events_async() -> list[dict]:
    return await asyncio.to_thread(get_today_events)
