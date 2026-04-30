"""
BioAgent — Módulo de Onboarding.
Genera el mensaje tutorial para usuarios nuevos.
"""


def get_tutorial_message(member_name: str) -> str:
    """Genera el mensaje de tutorial/bienvenida personalizado."""
    return f"""👋 *¡Hola, {member_name}! Soy PokeBot, tu asistente personal y del equipo.*

Te cuento rápido lo que puedo hacer por ti:

📋 *TAREAS Y LISTAS*
• _"Tarea: [nombre], [1/2/3], [fecha]"_ → Creo una tarea
  _(1=🔴Urgente, 2=🟡Importante, 3=🟢Normal)_
• _"Agrega [ítem] a mi lista de [categoría]"_ → Listas de compras, hogar, etc.
• _"¿Qué pendientes tengo?"_ → Resumen inteligente

⏰ *RECORDATORIOS*
• _"Recuérdame a las 3pm que..."_ → Te aviso puntual
• _"En 2 horas avísame de..."_ → Recordatorio relativo
• _"Recuérdale a Michelle que..."_ → Le aviso por privado

📅 *AGENDA (en el grupo)*
• _"Bot, agenda reunión el jueves a las 5pm"_
• _"Bot, ¿cómo vamos?"_ → Tablero de avance del equipo

💪 *HÁBITOS*
• _"Quiero trackear: ejercicio, lectura, agua"_
• A las 9 PM te pregunto cómo te fue

💚 *SALUD Y BIENESTAR*
• Pregúntame sobre sueño, suplementos, nutrición

🎤 *AUDIO*
• ¡Puedes enviarme notas de voz! Las transcribo y proceso igual _(próximamente)_

🧠 *MEMORIA*
• Todo lo importante que me digas, lo recuerdo para siempre
• _"Soy alérgico al gluten"_ → Guardado en tu perfil

⚠️ *IMPORTANTE:* Para que pueda enviarte briefings matutinos y recordatorios, necesito que interactúes conmigo al menos una vez al día. Si no me escribes en 24h, no podré enviarte mensajes hasta que me hables de nuevo (es una restricción de WhatsApp).

En el *grupo de investigación*, respondo cuando digan "Bot" o "PokeBot".

Escribe *"ayuda"* en cualquier momento para ver esta guía de nuevo.

*¡Escríbeme cualquier cosa para empezar!* 🚀"""
