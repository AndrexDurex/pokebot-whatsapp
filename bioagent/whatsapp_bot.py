"""
BioAgent — Handler principal para WhatsApp Cloud API.
Motor de conversación con OpenRouter (OpenAI standard) + memoria + RAG.
"""
import asyncio
import logging
import socket
import aiohttp
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import time

_processed_messages = {}

from bioagent.config import (
    WHATSAPP_TOKEN, WHATSAPP_PHONE_ID, BOT_NAME, SYSTEM_PROMPT, 
    OPENROUTER_API_KEY, OPENROUTER_MODEL, OWNER_PHONE_NUMBER
)
from bioagent import rag, memory, calendar_service, tasks, habits, lists, team_members, team_tasks

logger = logging.getLogger(__name__)

# Cliente de OpenRouter
_ai_client = None

# Historial en memoria (fallback)
_conversation_history: dict[str, list] = {}

async def send_whatsapp_message(to_number: str, text: str) -> None:
    """Envía un mensaje de texto a través de WhatsApp Cloud API."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        logger.error("❌ Faltan credenciales de WhatsApp.")
        return

    url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    text = text.replace("**", "*")
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }
    
    connector = aiohttp.TCPConnector(family=socket.AF_INET, limit=1, force_close=True)
    timeout = aiohttp.ClientTimeout(total=15.0)
    
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status >= 400:
                    body = await response.text()
                    logger.error(f"❌ WhatsApp API error ({response.status}): {body}")
                else:
                    logger.info(f"✅ Mensaje enviado exitosamente a {to_number}")
    except Exception as e:
        logger.error(f"❌ Error enviando WhatsApp: {e}")

import contextvars
_current_user_id = contextvars.ContextVar('current_user_id')

# ── Herramientas (Tools) ───────────────────────────────────────────────────────

# --- Tareas (con prioridad y deadline) ---
async def add_task_tool(title: str, priority: int = 3, category: str = "general", due_date: str = None) -> str:
    user_id = _current_user_id.get()
    result = await asyncio.to_thread(tasks.add_task, user_id, title=title, priority=priority, category=category, due_date=due_date)
    p_emoji = tasks.PRIORITY_EMOJI.get(tasks._normalize_priority(priority), "🟢")
    return f"{p_emoji} Tarea '{title}' creada con ID {result}" if result else "Error en Firebase."

async def complete_task_tool(task_id: str) -> str:
    user_id = _current_user_id.get()
    success = await asyncio.to_thread(tasks.complete_task, user_id, task_id)
    return f"✅ Tarea {task_id} completada." if success else "No encontrada."

# --- Listas simples (compras, hogar, farmacia, etc.) ---
async def add_list_item_tool(category: str, name: str) -> str:
    user_id = _current_user_id.get()
    result = await asyncio.to_thread(lists.add_item, user_id, category, name)
    return f"'{name}' agregado a lista [{category}] con ID {result}" if result else "Error en Firebase."

async def check_list_item_tool(category: str, item_id: str) -> str:
    user_id = _current_user_id.get()
    success = await asyncio.to_thread(lists.check_item, user_id, category, item_id)
    return f"✅ Ítem tachado de [{category}]." if success else "No encontrado."

async def get_list_tool(category: str) -> str:
    user_id = _current_user_id.get()
    items = await asyncio.to_thread(lists.get_list, user_id, category)
    if not items:
        return f"La lista [{category}] está vacía."
    lines = [f"📝 Lista *{category.upper()}*:"]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item['name']} (ID: {item['id']})")
    return "\n".join(lines)

async def add_calendar_event_tool(title: str, start_iso: str, end_iso: str, description: str = "", color_id: str = None, recurrence_rule: str = None, calendar_type: str = "main") -> str:
    created = await calendar_service.create_event_async(title, start_iso, end_iso, description, color_id, recurrence_rule, calendar_type)
    return f"Evento '{title}' creado el {start_iso} en {calendar_type}." if created else "Error en Calendar."

async def update_calendar_event_tool(event_id: str, title: str = None, start_iso: str = None, end_iso: str = None, description: str = None, color_id: str = None) -> str:
    result = await calendar_service.update_event_async(event_id, title, start_iso, end_iso, description, color_id)
    return f"Evento actualizado." if result else "Error en Calendar."

async def delete_calendar_event_tool(event_id: str) -> str:
    success = await asyncio.to_thread(calendar_service.delete_event, event_id)
    return f"Evento {event_id} eliminado." if success else "Error en Calendar."

async def add_habit_tool(name: str) -> str:
    user_id = _current_user_id.get()
    result = await asyncio.to_thread(habits.add_habit, user_id, name)
    return f"Hábito '{name}' creado con ID {result}" if result else "Error."

async def remove_habit_tool(habit_id: str) -> str:
    user_id = _current_user_id.get()
    success = await asyncio.to_thread(habits.remove_habit, user_id, habit_id)
    return f"Hábito {habit_id} eliminado." if success else "Error."

async def log_habit_tool(habit_id: str, date_iso: str, completed: bool) -> str:
    user_id = _current_user_id.get()
    success = await asyncio.to_thread(habits.log_habit, user_id, habit_id, date_iso, completed)
    status = "✅" if completed else "❌"
    return f"Hábito {habit_id} registrado como {status} para {date_iso}." if success else "Error."

async def schedule_reminder_tool(text: str, trigger_iso: str) -> str:
    from bioagent import reminders
    user_id = _current_user_id.get()
    rem_id = await asyncio.to_thread(reminders.add_reminder, user_id, text, trigger_iso)
    return f"Recordatorio programado con ID {rem_id}." if rem_id else "Error al programar."

async def update_profile_tool(action: str, key: str, value: str = None) -> str:
    user_id = _current_user_id.get()
    profile = await asyncio.to_thread(memory.get_profile, user_id)
    if not profile: profile = {}
    
    if action == "add" or action == "update":
        profile[key] = value
    elif action == "delete" and key in profile:
        del profile[key]
        
    success = await asyncio.to_thread(memory.save_profile, user_id, profile)
    return f"Perfil actualizado: {key}={value}" if success else "Error al actualizar perfil."

# Mapeo de funciones para ejecución dinámica
AVAILABLE_TOOLS = {
    "add_task_tool": add_task_tool,
    "complete_task_tool": complete_task_tool,
    "add_list_item_tool": add_list_item_tool,
    "check_list_item_tool": check_list_item_tool,
    "get_list_tool": get_list_tool,
    "add_calendar_event_tool": add_calendar_event_tool,
    "update_calendar_event_tool": update_calendar_event_tool,
    "delete_calendar_event_tool": delete_calendar_event_tool,
    "add_habit_tool": add_habit_tool,
    "remove_habit_tool": remove_habit_tool,
    "log_habit_tool": log_habit_tool,
    "schedule_reminder_tool": schedule_reminder_tool,
    "update_profile_tool": update_profile_tool,
}

# Definición de schemas para OpenRouter
OPENROUTER_TOOLS = [
    # --- TAREAS (pendientes con prioridad y deadline) ---
    {
        "type": "function",
        "function": {
            "name": "add_task_tool",
            "description": "Crea una TAREA con prioridad y fecha límite. Usa esto para pendientes, entregas, proyectos. NO para listas de compras.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título de la tarea."},
                    "priority": {"type": "integer", "enum": [1, 2, 3], "description": "1=Urgente, 2=Importante, 3=Normal (default)."},
                    "category": {"type": "string", "description": "Categoría: tesis, lab, general, pagos, etc."},
                    "due_date": {"type": "string", "description": "Fecha límite en formato YYYY-MM-DD."}
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task_tool",
            "description": "Marca una tarea como completada usando su ID.",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"]
            }
        }
    },
    # --- LISTAS (ítems simples: compras, hogar, farmacia, etc.) ---
    {
        "type": "function",
        "function": {
            "name": "add_list_item_tool",
            "description": "Agrega un ítem a una LISTA simple (compras, hogar, farmacia, etc.). Usa esto para cosas que se compran o se tachan, NO para tareas con deadline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Nombre de la lista: compras, hogar, farmacia, etc."},
                    "name": {"type": "string", "description": "Nombre del ítem a agregar."}
                },
                "required": ["category", "name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_list_item_tool",
            "description": "Tacha/marca como comprado un ítem de una lista usando su ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Nombre de la lista."},
                    "item_id": {"type": "string", "description": "ID del ítem a tachar."}
                },
                "required": ["category", "item_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_list_tool",
            "description": "Muestra todos los ítems pendientes de una lista específica.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Nombre de la lista: compras, hogar, farmacia, etc."}
                },
                "required": ["category"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_calendar_event_tool",
            "description": "Crea un evento en Google Calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start_iso": {"type": "string"},
                    "end_iso": {"type": "string"},
                    "description": {"type": "string"},
                    "color_id": {"type": "string"},
                    "recurrence_rule": {"type": "string"},
                    "calendar_type": {
                        "type": "string",
                        "enum": ["main", "routine"],
                        "description": "El calendario destino: 'main' para eventos, reuniones y Tesis. 'routine' para rutinas de salud o timeboxing."
                    }
                },
                "required": ["title", "start_iso", "end_iso", "calendar_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_calendar_event_tool",
            "description": "Modifica un evento existente en Calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "title": {"type": "string"},
                    "start_iso": {"type": "string"},
                    "end_iso": {"type": "string"},
                    "description": {"type": "string"},
                    "color_id": {"type": "string"}
                },
                "required": ["event_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_calendar_event_tool",
            "description": "Elimina un evento de Calendar.",
            "parameters": {
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
                "required": ["event_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_habit_tool",
            "description": "Añade un nuevo hábito al tracker diario.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_habit_tool",
            "description": "Registra el cumplimiento de un hábito.",
            "parameters": {
                "type": "object",
                "properties": {
                    "habit_id": {"type": "string"},
                    "date_iso": {"type": "string"},
                    "completed": {"type": "boolean"}
                },
                "required": ["habit_id", "date_iso", "completed"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_reminder_tool",
            "description": "Programa un recordatorio que el bot enviará proactivamente en una fecha y hora exactas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "El texto del recordatorio."},
                    "trigger_iso": {"type": "string", "description": "Fecha y hora exacta en formato ISO 8601 (ej. 2026-04-22T15:30:00-05:00)."}
                },
                "required": ["text", "trigger_iso"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_profile_tool",
            "description": "Añade, actualiza o elimina información permanente en el perfil de memoria del usuario (ej. preferencias, alergias, rutinas base).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "update", "delete"]},
                    "key": {"type": "string", "description": "Una clave corta (ej. 'alergias', 'hora_dormir', 'odio_pescado')."},
                    "value": {"type": "string", "description": "El valor. Omitir si action='delete'."}
                },
                "required": ["action", "key"]
            }
        }
    }
]

async def handle_ai_response(user_number: str, user_text: str) -> None:
    """Invoca OpenRouter con soporte para Function Calling. Multi-usuario."""
    global _ai_client
    user_id = user_number
    _current_user_id.set(user_id)
    member_name = team_members.get_member_name(user_number)
    
    try:
        if _ai_client is None:
            from openai import AsyncOpenAI
            _ai_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

        # 1. Recuperar memoria y contexto
        history = await asyncio.to_thread(memory.build_openrouter_history, user_id)
        rag_context = await asyncio.to_thread(rag.search, user_text)
        agenda_context = await calendar_service.get_user_agenda_summary_async(user_id, days=3)
        tasks_context = await asyncio.to_thread(tasks.get_tasks_summary, user_id)
        lists_context = await asyncio.to_thread(lists.get_lists_summary, user_id)
        
        now_local = datetime.now(timezone.utc) - timedelta(hours=5)
        habits_context = await asyncio.to_thread(habits.get_habits_summary, user_id, now_local.strftime("%Y-%m-%d"))

        profile_data = await asyncio.to_thread(memory.get_profile, user_id)
        profile_context = ""
        if profile_data:
            profile_context = "## PERFIL PERMANENTE DEL USUARIO:\n" + "\n".join([f"- {k}: {v}" for k, v in profile_data.items()])

        # Construir prompt
        context_parts = []
        if profile_context: context_parts.append(profile_context)
        if rag_context: context_parts.append(rag_context)
        if agenda_context: context_parts.append(agenda_context)
        if tasks_context: context_parts.append(tasks_context)
        if lists_context: context_parts.append(lists_context)
        if habits_context: context_parts.append(habits_context)
        
        # Tareas del equipo asignadas a este usuario
        team_context = await asyncio.to_thread(team_tasks.get_team_tasks_summary_for_user, user_id)
        if team_context: context_parts.append(team_context)
        
        system_msg = f"{SYSTEM_PROMPT}\n\nUSUARIO ACTUAL: {member_name}\n\nCONTEXTO ACTUAL:\n" + "\n\n".join(context_parts)
        
        messages = [{"role": "system", "content": system_msg}] + history + [{"role": "user", "content": user_text}]

        # 2. Bucle de ejecución de IA + Herramientas
        for _ in range(5): # Max 5 saltos de herramientas
            for attempt in range(3):
                try:
                    response = await _ai_client.chat.completions.create(
                        model=OPENROUTER_MODEL,
                        messages=messages,
                        tools=OPENROUTER_TOOLS,
                        tool_choice="auto"
                    )
                    break
                except Exception as e:
                    if "Expecting value" in str(e) and attempt < 2:
                        logger.warning(f"⚠️ OpenRouter falló con JSONDecodeError. Reintentando ({attempt+1}/3)...")
                        await asyncio.sleep(2)
                    else:
                        raise
            
            msg = response.choices[0].message
            messages.append(msg)
            
            if not msg.tool_calls:
                bot_reply = msg.content
                logger.info(f"🧠 OpenRouter seleccionó el modelo: {response.model}")
                break
            
            # Ejecutar herramientas
            for tc in msg.tool_calls:
                func_name = tc.function.name
                args = json.loads(tc.function.arguments)
                logger.info(f"🛠️ Ejecutando: {func_name}({args})")
                
                func = AVAILABLE_TOOLS.get(func_name)
                if func:
                    result = await func(**args)
                else:
                    result = f"Error: herramienta {func_name} no encontrada."
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": func_name,
                    "content": result
                })
        else:
            bot_reply = "He realizado varias acciones, ¿en qué más puedo ayudarte?"

        if not bot_reply:
            bot_reply = "✅ Listo, he procesado tu solicitud."

        # 3. Guardar y enviar
        await asyncio.to_thread(memory.save_message, user_id, "user", user_text)
        await asyncio.to_thread(memory.save_message, user_id, "model", bot_reply)
        await send_whatsapp_message(user_number, bot_reply)

    except Exception as e:
        import traceback
        logger.error(f"❌ Error OpenRouter: {e}\n{traceback.format_exc()}")
        await send_whatsapp_message(user_number, "⚠️ Tuve un problema con mi motor de IA. Intenta de nuevo.")

async def process_whatsapp_message(body: Dict[str, Any]) -> None:
    """
    Procesa el JSON entrante del webhook de WhatsApp.
    DEPRECATED: Usar router.route_message() en su lugar.
    Se mantiene por compatibilidad con código antiguo.
    """
    try:
        entry = body.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        if "messages" not in value: return
            
        for msg in value["messages"]:
            if msg.get("type") != "text": continue
            
            from_number = msg["from"]
            text_body = msg["text"]["body"]

            logger.info(f"📥 WhatsApp de {from_number}: {text_body[:30]}...")
            await handle_ai_response(from_number, text_body)
    except Exception as e:
        logger.error(f"❌ Error webhook: {e}")
