"""
BioAgent — Router principal de mensajes.
Detecta si el mensaje viene de un grupo o de un chat privado
y lo enruta al handler correcto.

Flujo:
  Mensaje entrante
    ├── ¿Autorizado? → No → "🔒 Acceso restringido"
    ├── ¿Primera vez? → Sí → Enviar tutorial de onboarding
    ├── ¿Es de un grupo? → Sí → team_bot.handle_group_message()
    └── ¿Es privado? → Sí → whatsapp_bot.handle_ai_response()
"""
import asyncio
import logging
import time
from typing import Dict, Any

from bioagent import team_members, onboarding, team_bot, team_tasks
from bioagent.whatsapp_bot import (
    handle_ai_response,
    send_whatsapp_message,
)

logger = logging.getLogger(__name__)

# Cache de mensajes procesados para deduplicación (compartido)
_processed_messages: dict[str, float] = {}


async def route_message(body: Dict[str, Any]) -> None:
    """
    Punto de entrada principal para todos los mensajes de WhatsApp.
    Reemplaza a process_whatsapp_message del bot personal.
    """
    try:
        entry = body.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        if "messages" not in value:
            return

        for msg in value["messages"]:
            # === Deduplicación ===
            msg_id = msg.get("id")
            if msg_id:
                if msg_id in _processed_messages:
                    logger.info(f"⏭️ Mensaje {msg_id} ya procesado. Ignorando duplicado.")
                    continue
                _processed_messages[msg_id] = time.time()

                # Limpiar cache viejo
                if len(_processed_messages) > 1000:
                    current = time.time()
                    stale = [k for k, v in _processed_messages.items() if current - v > 3600]
                    for k in stale:
                        del _processed_messages[k]

            from_number = msg["from"]

            # === Autorización ===
            if not team_members.is_authorized(from_number):
                logger.warning(f"🚫 Número no autorizado: {from_number}")
                await send_whatsapp_message(from_number, "🔒 Acceso restringido. Este bot es privado.")
                continue

            member_name = team_members.get_member_name(from_number)

            # === Detectar tipo de mensaje ===
            msg_type = msg.get("type", "unknown")

            # Por ahora solo procesamos texto. Audio se agregará en Fase 7.
            if msg_type == "text":
                text_body = msg["text"]["body"]
            elif msg_type == "audio":
                # Placeholder: en Fase 7 se transcribirá con ElevenLabs Scribe
                await send_whatsapp_message(from_number,
                    "🎤 He recibido tu nota de voz. La funcionalidad de audio estará disponible pronto.")
                continue
            else:
                continue

            logger.info(f"📥 [{member_name}] ({from_number}): {text_body[:40]}...")

            # === Detectar grupo vs privado ===
            # WhatsApp Cloud API: los mensajes de grupo incluyen un campo "group_id"
            # en value.metadata o en el contexto del mensaje.
            # Si no existe group_id, es un mensaje privado (1:1).
            is_group = _is_group_message(msg, value)

            if is_group:
                # === Modo Grupo: Project Manager ===
                # Solo responde si lo mencionan o usan palabras clave
                if _should_respond_in_group(text_body):
                    logger.info(f"🏢 [{member_name}] en grupo: {text_body[:40]}...")
                    group_id = _get_group_id(msg, value)
                    await team_bot.handle_group_message(from_number, text_body, group_id)
                else:
                    # Ignora mensajes del grupo que no lo mencionan
                    logger.debug(f"💤 Mensaje de grupo ignorado (sin mención)")
            else:
                # === Modo Privado: Asistente Personal ===

                # Onboarding: primera vez del usuario
                if not team_members.is_onboarded(from_number):
                    logger.info(f"🎓 Onboarding para {member_name} ({from_number})")
                    tutorial_msg = onboarding.get_tutorial_message(member_name)
                    await send_whatsapp_message(from_number, tutorial_msg)
                    team_members.mark_onboarded(from_number)
                    # Procesar también su mensaje actual
                    if text_body.lower().strip() in ("hola", "hi", "hello", "hey"):
                        continue  # Solo el tutorial es suficiente para un saludo

                # Comando de ayuda
                if text_body.lower().strip() in ("ayuda", "help", "tutorial", "bot ayuda", "bot tutorial"):
                    tutorial_msg = onboarding.get_tutorial_message(member_name)
                    await send_whatsapp_message(from_number, tutorial_msg)
                    continue

                # Procesar con el asistente de IA
                await handle_ai_response(from_number, text_body)

    except Exception as e:
        logger.error(f"❌ Error en router: {e}")


def _is_group_message(msg: dict, value: dict) -> bool:
    """
    Detecta si un mensaje proviene de un grupo de WhatsApp.
    En la Cloud API, los mensajes de grupo tienen un campo 'group_id'
    en el contexto del mensaje o en el metadata.
    """
    # Método 1: campo directo en el mensaje
    if "group_id" in msg:
        return True
    # Método 2: en el contexto (para mensajes de grupo en Cloud API v18+)
    context = msg.get("context", {})
    if "group_id" in context:
        return True
    # Método 3: metadata del valor
    metadata = value.get("metadata", {})
    if metadata.get("display_phone_number") != metadata.get("phone_number_id"):
        # Heurística: en grupos, el display_phone_number puede diferir
        pass
    return False


def _should_respond_in_group(text: str) -> bool:
    """
    Determina si el bot debe responder a un mensaje del grupo.
    Solo responde si lo mencionan o usan palabras clave.
    """
    text_lower = text.lower().strip()
    # Palabras clave de activación
    triggers = [
        "bot,", "bot ", "@bot", "pokebot", "@pokebot",
        "tarea", "reunión", "reunion", "pendientes",
        "cómo vamos", "como vamos", "tablero", "asigna",
    ]
    return any(trigger in text_lower for trigger in triggers)


def _get_group_id(msg: dict, value: dict) -> str:
    """Extrae el group_id del mensaje de grupo."""
    if "group_id" in msg:
        return msg["group_id"]
    context = msg.get("context", {})
    if "group_id" in context:
        return context["group_id"]
    return ""
