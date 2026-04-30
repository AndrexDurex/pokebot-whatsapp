"""
BioAgent — Módulo de gestión de TAREAS con Firebase RTDB.
Las tareas son pendientes con prioridad, deadline y responsable.
SEPARADO de Listas (ver lists.py para compras, hogar, etc.)

Prioridad numérica:
  1 = 🔴 Urgente (vence hoy/mañana, crítico)
  2 = 🟡 Importante (tiene deadline esta semana)
  3 = 🟢 Normal (sin urgencia, default)

Estructura en RTDB:
  users/{user_id}/tasks/{task_id}/
    title: str
    done: bool
    priority: int  (1, 2 o 3)
    category: str  (tesis, lab, general, etc.)
    due_date: str|None  (ISO date)
    notes: str
    created_at: int (timestamp)
"""
import logging
import time
from typing import Optional

from firebase_admin import db

from bioagent.memory import _init_firebase

logger = logging.getLogger(__name__)

# Mapeo de prioridad: soporta tanto número como palabra
PRIORITY_MAP = {
    # Numéricos
    "1": 1, "2": 2, "3": 3,
    1: 1, 2: 2, 3: 3,
    # Palabras en español
    "urgente": 1, "alta": 1,
    "importante": 2, "media": 2,
    "normal": 3, "baja": 3,
}

PRIORITY_EMOJI = {1: "🔴", 2: "🟡", 3: "🟢"}
PRIORITY_LABEL = {1: "Urgente", 2: "Importante", 3: "Normal"}


def _normalize_priority(priority) -> int:
    """Convierte cualquier formato de prioridad al número 1/2/3."""
    if priority is None:
        return 3
    val = PRIORITY_MAP.get(priority)
    if val is not None:
        return val
    # Intentar con string lowercase
    if isinstance(priority, str):
        val = PRIORITY_MAP.get(priority.lower().strip())
        if val is not None:
            return val
    return 3  # Default: Normal


def add_task(
    user_id: str,
    title: str,
    priority=3,
    category: str = "general",
    due_date: Optional[str] = None,
    notes: str = "",
) -> Optional[str]:
    """
    Crea una nueva tarea. Retorna el task_id o None si falla.
    priority: 1 (urgente), 2 (importante), 3 (normal/default)
    """
    if not _init_firebase():
        return None
    try:
        ref = db.reference(f"users/{user_id}/tasks")
        task = {
            "title": title,
            "done": False,
            "priority": _normalize_priority(priority),
            "category": category,
            "due_date": due_date or "",
            "notes": notes,
            "created_at": int(time.time()),
        }
        result = ref.push(task)
        p_emoji = PRIORITY_EMOJI.get(task["priority"], "🟢")
        logger.info(f"✅ Tarea creada {p_emoji}: {title} ({result.key})")
        return result.key
    except Exception as e:
        logger.error(f"❌ add_task error: {e}")
        return None


def get_tasks(user_id: str, only_pending: bool = True) -> list[dict]:
    """
    Retorna las tareas del usuario.
    Cada tarea incluye 'id' además de sus datos.
    Ordenadas por prioridad: 1 (urgente) → 2 (importante) → 3 (normal).
    """
    if not _init_firebase():
        return []
    try:
        ref = db.reference(f"users/{user_id}/tasks")
        data = ref.order_by_child("created_at").get()
        if not data:
            return []
        tasks = []
        for task_id, task_data in data.items():
            if only_pending and task_data.get("done", False):
                continue
            # Migrar prioridades antiguas (string) a número
            raw_priority = task_data.get("priority", 3)
            task_data["priority"] = _normalize_priority(raw_priority)
            tasks.append({"id": task_id, **task_data})
        # Ordenar: 1 → 2 → 3
        tasks.sort(key=lambda t: t.get("priority", 3))
        return tasks
    except Exception as e:
        logger.error(f"❌ get_tasks error: {e}")
        return []


def complete_task(user_id: str, task_id: str) -> bool:
    """Marca una tarea como completada."""
    if not _init_firebase():
        return False
    try:
        ref = db.reference(f"users/{user_id}/tasks/{task_id}")
        ref.update({"done": True, "completed_at": int(time.time())})
        logger.info(f"✅ Tarea completada: {task_id}")
        return True
    except Exception as e:
        logger.error(f"❌ complete_task error: {e}")
        return False


def delete_task(user_id: str, task_id: str) -> bool:
    """Elimina una tarea permanentemente."""
    if not _init_firebase():
        return False
    try:
        db.reference(f"users/{user_id}/tasks/{task_id}").delete()
        return True
    except Exception as e:
        logger.error(f"❌ delete_task error: {e}")
        return False


def format_tasks_list(tasks: list[dict]) -> str:
    """Formatea la lista de tareas para mostrar en WhatsApp."""
    if not tasks:
        return "✅ No tienes tareas pendientes."

    lines = ["📋 *Tareas pendientes:*\n"]
    for i, t in enumerate(tasks, 1):
        p = t.get("priority", 3)
        emoji = PRIORITY_EMOJI.get(p, "🟢")
        title = t.get("title", "Sin título")
        cat = t.get("category", "")
        due = t.get("due_date", "")
        line = f"{emoji} {i}. {title}"
        if cat and cat != "general":
            line += f" _[{cat}]_"
        if due:
            line += f" — 📆 {due}"
        lines.append(line)
    return "\n".join(lines)


def get_tasks_summary(user_id: str) -> str:
    """Resumen de tareas para inyectar en el prompt del LLM."""
    tasks = get_tasks(user_id, only_pending=True)
    if not tasks:
        return ""

    # Agrupar por categoría
    grouped = {}
    for t in tasks:
        cat = t.get("category", "general").upper()
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(t)

    lines = ["## Tareas Pendientes del Usuario:"]
    for cat, items in grouped.items():
        lines.append(f"\n### Categoría: {cat}")
        for t in items[:15]:
            p = t.get("priority", 3)
            emoji = PRIORITY_EMOJI.get(p, "🟢")
            label = PRIORITY_LABEL.get(p, "Normal")
            title = t.get("title", "")
            due = t.get("due_date", "")
            task_id = t.get("id", "")

            line = f"- {emoji} [{label}] {title} (ID: {task_id})"
            if due:
                line += f" | Vence: {due}"
            lines.append(line)

        if len(items) > 15:
            lines.append(f"- ... y {len(items)-15} tareas más.")

    return "\n".join(lines)
