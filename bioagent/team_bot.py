"""
BioAgent — Handler del modo grupo (Project Manager).
Se activa cuando un mensaje viene del grupo de WhatsApp.
Gestiona tareas grupales, reuniones y tablero de avance.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from bioagent.config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from bioagent.whatsapp_bot import send_whatsapp_message, _ai_client
from bioagent import team_tasks, team_members, calendar_service, memory

logger = logging.getLogger(__name__)

# ── System Prompt para modo grupo ──────────────────────────────────────────────

TEAM_SYSTEM_PROMPT = """
Eres PokeBot en modo Project Manager para un grupo de investigación de 4 personas.
Tu rol es gestionar tareas del equipo, coordinar reuniones y dar visibilidad del progreso.

MIEMBROS DEL EQUIPO:
- André (Admin) — +51 931 048 021
- Joaquín — +51 975 404 354
- Michelle — +51 997 875 950
- Daniela — +51 980 436 235

TU PERSONALIDAD EN GRUPO:
- Profesional pero cercano.
- Respuestas concisas (el grupo no quiere muros de texto).
- Usa emojis para claridad visual.
- Siempre confirma las acciones realizadas.

TUS CAPACIDADES:
1. ASIGNAR TAREAS: Crea tareas asignadas a miembros con prioridad (1=🔴, 2=🟡, 3=🟢) y deadline.
2. COMPLETAR TAREAS: Marca tareas como listas cuando un miembro lo pida.
3. TABLERO: Muestra el estado general del proyecto.
4. REUNIONES: Agenda reuniones en el calendario grupal.

REGLAS:
- Para asignar, necesitas: título, a quién, y opcionalmente prioridad y fecha.
- Identifica al asignado por nombre (Joaquín, Michelle, Daniela, André).
- Cuando completes una tarea, celebra brevemente al equipo.
- El campo QUIEN_HABLA te dice quién envió el mensaje.
"""

# ── Herramientas del modo grupo ────────────────────────────────────────────────

# Context var para saber quién habla en el grupo
import contextvars
_group_sender = contextvars.ContextVar('group_sender')


def _resolve_member_phone(name: str) -> Optional[str]:
    """Resuelve un nombre a su número de teléfono."""
    name_lower = name.lower().strip()
    for phone, data in team_members.AUTHORIZED_MEMBERS.items():
        if data["name"].lower() == name_lower:
            return phone
    return None


async def assign_team_task_tool(
    title: str,
    assigned_to_name: str,
    priority: int = 3,
    due_date: str = None,
    category: str = "general",
) -> str:
    """Asigna una tarea a un miembro del equipo."""
    sender = _group_sender.get()
    target_phone = _resolve_member_phone(assigned_to_name)
    if not target_phone:
        return f"No encontré al miembro '{assigned_to_name}'. Miembros válidos: André, Joaquín, Michelle, Daniela."

    task_id = await asyncio.to_thread(
        team_tasks.add_team_task,
        title=title,
        assigned_to=target_phone,
        assigned_by=sender,
        priority=priority,
        due_date=due_date,
        category=category,
    )
    if not task_id:
        return "Error al crear la tarea."

    target_name = team_members.get_member_name(target_phone)
    p_emoji = team_tasks.PRIORITY_EMOJI.get(team_tasks._normalize_priority(priority), "🟢")

    # Notificar por DM al asignado
    due_str = f" Vence: {due_date}." if due_date else ""
    dm_msg = f"📌 *Nueva tarea del equipo:*\n{p_emoji} {title}{due_str}\n\nAsignada por {team_members.get_member_name(sender)}."
    asyncio.create_task(send_whatsapp_message(target_phone, dm_msg))

    return f"✅ Tarea asignada a {target_name}: {p_emoji} {title}" + (f" (vence {due_date})" if due_date else "")


async def complete_team_task_tool(task_id: str) -> str:
    """Marca una tarea grupal como completada."""
    success = await asyncio.to_thread(team_tasks.complete_team_task, task_id)
    if not success:
        return "No encontré esa tarea."
    sender_name = team_members.get_member_name(_group_sender.get())
    return f"✅ {sender_name} completó la tarea. ¡Buen trabajo! 💪"


async def get_team_board_tool() -> str:
    """Muestra el tablero de avance del proyecto."""
    board = await asyncio.to_thread(team_tasks.get_team_board)
    return board


async def schedule_team_meeting_tool(
    title: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
) -> str:
    """Agenda una reunión en el calendario grupal."""
    created = await calendar_service.create_team_event_async(title, start_iso, end_iso, description)
    if not created:
        return "Error al crear la reunión. ¿Está configurado el calendario grupal?"

    # Notificar a todos los miembros por DM
    for phone in team_members.get_all_member_numbers():
        name = team_members.get_member_name(phone)
        dm_msg = f"📅 *Reunión agendada:*\n{title}\n⏰ {start_iso[:16].replace('T', ' ')}\n\n_Les avisaré 15 min antes._"
        asyncio.create_task(send_whatsapp_message(phone, dm_msg))

    return f"✅ Reunión agendada: *{title}*\n📅 {start_iso[:16].replace('T', ' ')}"


# Mapeo de herramientas del grupo
TEAM_TOOLS = {
    "assign_team_task_tool": assign_team_task_tool,
    "complete_team_task_tool": complete_team_task_tool,
    "get_team_board_tool": get_team_board_tool,
    "schedule_team_meeting_tool": schedule_team_meeting_tool,
}

# Schemas para OpenRouter
TEAM_OPENROUTER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "assign_team_task_tool",
            "description": "Asigna una tarea a un miembro del equipo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título de la tarea."},
                    "assigned_to_name": {"type": "string", "description": "Nombre del miembro: André, Joaquín, Michelle o Daniela."},
                    "priority": {"type": "integer", "enum": [1, 2, 3], "description": "1=Urgente, 2=Importante, 3=Normal."},
                    "due_date": {"type": "string", "description": "Fecha límite YYYY-MM-DD."},
                    "category": {"type": "string", "description": "Categoría: investigación, documentación, etc."},
                },
                "required": ["title", "assigned_to_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_team_task_tool",
            "description": "Marca una tarea grupal como completada.",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_team_board_tool",
            "description": "Muestra el tablero de avance del proyecto con todas las tareas y su estado.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_team_meeting_tool",
            "description": "Agenda una reunión en el calendario grupal del equipo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Nombre de la reunión."},
                    "start_iso": {"type": "string", "description": "Inicio en ISO 8601 con timezone."},
                    "end_iso": {"type": "string", "description": "Fin en ISO 8601 con timezone."},
                    "description": {"type": "string"},
                },
                "required": ["title", "start_iso", "end_iso"],
            },
        },
    },
]


# ── Handler principal del modo grupo ──────────────────────────────────────────

async def handle_group_message(from_number: str, text: str, group_id: str = "") -> None:
    """Procesa un mensaje del grupo usando el modo Project Manager."""
    global _ai_client
    _group_sender.set(from_number)

    try:
        if _ai_client is None:
            from openai import AsyncOpenAI
            _ai_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

        sender_name = team_members.get_member_name(from_number)
        now_local = datetime.now(timezone.utc) - timedelta(hours=5)

        # Contexto del equipo
        board_context = await asyncio.to_thread(team_tasks.get_team_board)
        team_events = await calendar_service.get_team_events_async(days=7)
        events_text = ""
        if team_events:
            events_lines = ["📅 *Eventos del equipo:*"]
            for e in team_events:
                start = e["start"].replace("T", " ").split("+")[0][:16]
                events_lines.append(f"• {start} — {e['title']}")
            events_text = "\n".join(events_lines)

        context = f"""QUIEN_HABLA: {sender_name} ({from_number})
FECHA/HORA: {now_local.strftime("%Y-%m-%d %H:%M")}

{board_context}

{events_text}"""

        system_msg = f"{TEAM_SYSTEM_PROMPT}\n\nCONTEXTO:\n{context}"

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": text},
        ]

        # Bucle de herramientas
        for _ in range(5):
            for attempt in range(3):
                try:
                    response = await _ai_client.chat.completions.create(
                        model=OPENROUTER_MODEL,
                        messages=messages,
                        tools=TEAM_OPENROUTER_TOOLS,
                        tool_choice="auto",
                    )
                    break
                except Exception as e:
                    if "Expecting value" in str(e) and attempt < 2:
                        logger.warning(f"⚠️ OpenRouter retry grupo ({attempt+1}/3)...")
                        await asyncio.sleep(2)
                    else:
                        raise

            msg = response.choices[0].message
            messages.append(msg)

            if not msg.tool_calls:
                bot_reply = msg.content
                break

            for tc in msg.tool_calls:
                func_name = tc.function.name
                args = json.loads(tc.function.arguments)
                logger.info(f"🏢🛠️ Grupo: {func_name}({args})")

                func = TEAM_TOOLS.get(func_name)
                if func:
                    result = await func(**args)
                else:
                    result = f"Herramienta {func_name} no encontrada."

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": func_name,
                    "content": result,
                })
        else:
            bot_reply = "He procesado las acciones del equipo. ¿Algo más?"

        if not bot_reply:
            bot_reply = "✅ Listo."

        # En modo grupo, respondemos al remitente (la API de WhatsApp no permite
        # enviar directamente al grupo, sino al número del remitente).
        # Para enviar al grupo se necesitaría el group_id con soporte específico.
        await send_whatsapp_message(from_number, bot_reply)

    except Exception as e:
        import traceback
        logger.error(f"❌ Error grupo: {e}\n{traceback.format_exc()}")
        await send_whatsapp_message(from_number, "⚠️ Error procesando la solicitud del equipo.")
