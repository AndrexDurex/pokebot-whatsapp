"""
BioAgent — Handler principal para WhatsApp Cloud API.
Motor de conversación con Gemini 2.5 Flash + memoria + RAG, adaptado para recibir Webhooks HTTP.
"""
import asyncio
import logging
import socket
import aiohttp
from typing import Dict, Any

from bioagent.config import (
    WHATSAPP_TOKEN, WHATSAPP_PHONE_ID, BOT_NAME, SYSTEM_PROMPT, 
    GEMINI_API_KEY, GEMINI_MODEL, OWNER_PHONE_NUMBER
)
from bioagent import rag, memory, calendar_service, tasks

logger = logging.getLogger(__name__)

# Motor de Gemini
_gemini_model = None

# Historial en memoria (fallback)
_conversation_history: dict[str, list] = {}

async def send_whatsapp_message(to_number: str, text: str) -> None:
    """Envía un mensaje de texto a través de WhatsApp Cloud API.
    Usa aiohttp con resolución DNS forzada a IPv4 y connector fresco por intento."""
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
    
    max_retries = 3
    
    for attempt in range(max_retries):
        # Connector FRESCO en cada intento: fuerza IPv4 via family=AF_INET
        # Esto hace que aiohttp resuelva DNS internamente pero SOLO a IPv4
        # El hostname se mantiene en la URL para que TLS valide el certificado correctamente
        connector = aiohttp.TCPConnector(
            family=socket.AF_INET,  # Solo IPv4
            limit=1,
            force_close=True,
        )
        timeout = aiohttp.ClientTimeout(total=15.0)
        
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    body = await response.text()
                    if response.status >= 400:
                        logger.error(f"❌ WhatsApp API error ({response.status}): {body}")
                        return
                    logger.info(f"✅ Mensaje enviado exitosamente a {to_number}")
                    return
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            logger.warning(f"⚠️ Fallo red ({e.__class__.__name__}) intento {attempt+1}/{max_retries}")
            await asyncio.sleep(2 * (attempt + 1))
        except Exception as e:
            import traceback
            logger.error(f"❌ Excepción enviando WhatsApp: {e}\n{traceback.format_exc()}")
            return
    
    logger.error(f"❌ No se pudo enviar mensaje a {to_number} después de {max_retries} intentos.")

async def process_whatsapp_message(body: Dict[str, Any]) -> None:
    """Procesa el JSON entrante del webhook de WhatsApp."""
    try:
        # Navegamos el payload complejo de WhatsApp
        entry = body.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        
        # Ignoramos mensajes de sistema o status updates (entregado/leído)
        if "messages" not in value:
            return
            
        messages = value["messages"]
        contacts = value.get("contacts", [])
        
        for msg in messages:
            # Solo procesamos mensajes de texto por ahora
            if msg.get("type") != "text":
                continue
                
            from_number = msg["from"]     # El número que escribió
            text_body = msg["text"]["body"]  # El texto del mensaje
            
            # ── Guard de autorización ──
            if OWNER_PHONE_NUMBER and not from_number.endswith(OWNER_PHONE_NUMBER[-8:]):
                # Validamos terminación por posibles códigos de país ej: 521 vs 52
                logger.warning(f"🔒 Acceso denegado al número {from_number}")
                await send_whatsapp_message(from_number, "🔒 Acceso restringido. Soy un asistente privado.")
                continue

            logger.info(f"📥 WhatsApp de {from_number}: {text_body[:30]}...")
            
            # Lanzamos el procesamiento de IA
            await handle_ai_response(from_number, text_body)

    except Exception as e:
        logger.error(f"❌ Error procesando webhook de WhatsApp: {e}")

import contextvars
_current_user_id = contextvars.ContextVar('current_user_id')

def add_item_tool(title: str, priority: str = "media", category: str = "general") -> str:
    """
    Agrega una tarea o un ítem a una lista en la base de datos del usuario.
    Usa esta herramienta cuando te pidan anotar algo pendiente, agregar algo a la lista de compras, etc.
    
    Args:
        title: El título de la tarea o ítem a comprar.
        priority: Nivel de prioridad ("alta", "media" o "baja").
        category: El nombre de la lista o categoría. Ej: "compras_casa", "compras_super", "tesis", "general". 
                  Si es una lista nueva, simplemente inventa un nombre de categoría descriptivo.
    """
    try:
        user_id = _current_user_id.get()
        result = tasks.add_task(user_id, title=title, priority=priority, category=category)
        if result:
            return f"Ítem '{title}' agregado a la lista '{category}' con ID {result}"
        return "Error al agregar en Firebase."
    except Exception as e:
        return f"Error interno: {e}"

def mark_item_done_tool(item_id: str) -> str:
    """
    Marca una tarea o ítem de una lista como completado/comprado usando su ID.
    Usa esta herramienta cuando el usuario te indique que ya hizo una tarea o compró un ítem.
    
    Args:
        item_id: El ID único del ítem (se te proporciona en el resumen de tareas).
    """
    try:
        user_id = _current_user_id.get()
        success = tasks.complete_task(user_id, item_id)
        if success:
            return f"Ítem {item_id} marcado como completado."
        return f"Error: No se encontró el ítem {item_id} o no se pudo completar."
    except Exception as e:
        return f"Error interno: {e}"

def add_calendar_event_tool(title: str, start_iso: str, end_iso: str, description: str = "", color_id: str = None) -> str:
    """
    Crea un bloque de tiempo (evento) en el Google Calendar del usuario.
    Úsalo para agendar rutinas, citas médicas, bloques de Tesis o recordatorios precisos.
    Si hay conflicto de horarios, debes eliminar o reprogramar el evento anterior si la Tesis tiene prioridad.
    
    Args:
        title: Título del evento (ej: "Entrenamiento de Fuerza").
        start_iso: Fecha y hora de inicio en formato ISO (ej: "2026-04-22T10:00:00"). Debe ser zona horaria local.
        end_iso: Fecha y hora de fin en formato ISO (ej: "2026-04-22T11:00:00").
        description: Detalles del evento, rutinas a seguir, listas de compras, etc.
        color_id: ID de color opcional ('1'=Lavanda, '4'=Rosa, '8'=Grafito, '11'=Tomate). Usa tomates para la Tesis.
    """
    try:
        # calendar_service ya es síncrono internamente para create_event
        created = calendar_service.create_event(title, start_iso, end_iso, description, color_id)
        if created:
            return f"Evento '{title}' creado exitosamente el {start_iso}."
        return "Error al crear el evento en Google Calendar."
    except Exception as e:
        return f"Error interno de Calendar: {e}"

def delete_calendar_event_tool(event_id: str) -> str:
    """
    Elimina un evento de Google Calendar usando su ID.
    Úsalo cuando el usuario cancele un evento o cuando necesites mover un bloque de tiempo por conflicto (lo borras y lo creas de nuevo).
    
    Args:
        event_id: El ID del evento (se te proporciona en el resumen de la agenda).
    """
    try:
        success = calendar_service.delete_event(event_id)
        if success:
            return f"Evento {event_id} eliminado exitosamente."
        return "Error al eliminar el evento de Google Calendar."
    except Exception as e:
        return f"Error interno de Calendar: {e}"

def update_calendar_event_tool(
    event_id: str,
    title: str = None,
    start_iso: str = None,
    end_iso: str = None,
    description: str = None,
    color_id: str = None,
) -> str:
    """
    Modifica un evento existente en Google Calendar. Solo actualiza los campos que se especifiquen.
    Úsalo para reprogramar horarios, renombrar eventos o cambiar descripciones.
    Primero obtén el ID del evento desde el resumen de la agenda.
    
    Args:
        event_id: El ID del evento a modificar (lo ves en el resumen de agenda).
        title: Nuevo título del evento (opcional).
        start_iso: Nueva fecha/hora de inicio en ISO (ej: '2026-04-28T10:00:00') (opcional).
        end_iso: Nueva fecha/hora de fin en ISO (ej: '2026-04-28T11:00:00') (opcional).
        description: Nueva descripción del evento (opcional).
        color_id: Nuevo color ('1'=Lavanda, '4'=Rosa, '8'=Grafito, '11'=Tomate) (opcional).
    """
    try:
        result = calendar_service.update_event(
            event_id=event_id,
            title=title,
            start_iso=start_iso,
            end_iso=end_iso,
            description=description,
            color_id=color_id,
        )
        if result:
            return f"Evento '{result.get('summary', event_id)}' actualizado exitosamente."
        return "Error al actualizar el evento en Google Calendar."
    except Exception as e:
        return f"Error interno de Calendar: {e}"

async def handle_ai_response(user_number: str, user_text: str) -> None:
    """Invoca la inteligencia y envía de vuelta a WhatsApp."""
    global _gemini_model
    
    # Tratar user_number como identifier para la memoria
    user_id = user_number 
    _current_user_id.set(user_id)
    
    try:
        # Inicializar cliente google.genai (nuevo SDK)
        if _gemini_model is None:
            from google import genai
            _gemini_model = genai.Client(api_key=GEMINI_API_KEY)

        # 1. Recuperar memoria (Firebase)
        firebase_history = await asyncio.to_thread(memory.build_gemini_history, user_id)
        history = firebase_history if firebase_history else _conversation_history.get(user_id, [])

        # 2. Contexto (RAG + Calendar + Tasks)
        rag_context = await asyncio.to_thread(rag.search, user_text)
        agenda_context = await calendar_service.get_agenda_summary_async(days=3)
        tasks_context = await asyncio.to_thread(tasks.get_tasks_summary, user_id)

        # Construir prompt enriquecido
        parts = []
        if rag_context: parts.append(rag_context)
        if agenda_context: parts.append(agenda_context)
        if tasks_context: parts.append(tasks_context)
        parts.append(f"## Consulta del usuario:\n{user_text}")
        enriched_prompt = "\n\n".join(parts)

        # 3. Invocar Gemini con reintentos para errores 503 de alta demanda
        from google.genai import types
        from google.genai.errors import ServerError

        all_contents = history + [{"role": "user", "parts": [{"text": enriched_prompt}]}]

        gemini_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[
                add_item_tool,
                mark_item_done_tool,
                add_calendar_event_tool,
                update_calendar_event_tool,
                delete_calendar_event_tool,
            ],
        )

        response = None
        for attempt in range(1, 4):  # hasta 3 intentos
            try:
                response = await asyncio.to_thread(
                    lambda: _gemini_model.models.generate_content(
                        model=GEMINI_MODEL,
                        contents=all_contents,
                        config=gemini_config,
                    )
                )
                break  # éxito, salir del loop
            except ServerError as se:
                if attempt < 3 and "503" in str(se):
                    wait = attempt * 3  # 3s, 6s
                    logger.warning(f"⚠️ Gemini 503 (intento {attempt}/3), reintentando en {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    raise  # reraise si ya agotamos intentos o es otro error
        
        # response.text puede ser None si el modelo solo devolvió function calls sin texto final
        bot_reply = response.text
        if not bot_reply:
            # Intentar extraer texto de los candidates
            try:
                bot_reply = response.candidates[0].content.parts[0].text
            except Exception:
                bot_reply = None
        
        if not bot_reply:
            logger.warning("⚠️ Gemini no devolvió texto. Posible función ejecutada sin respuesta final.")
            bot_reply = "✅ Listo, acción realizada."

        # 4. Guardar historiales
        await asyncio.to_thread(memory.save_message, user_id, "user", user_text)
        await asyncio.to_thread(memory.save_message, user_id, "model", bot_reply)
        _conversation_history[user_id] = history

        # 5. Enviar mensaje por WhatsApp
        await send_whatsapp_message(user_number, bot_reply)

    except Exception as e:
        import traceback
        logger.error(f"❌ Error en Gemini/WhatsApp: {e}\n{traceback.format_exc()}")
        await send_whatsapp_message(user_number, "⚠️ Tuve un problema procesando tu consulta. Intenta de nuevo en un momento.")

