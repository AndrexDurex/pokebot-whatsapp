"""
BioAgent — Gestión de tareas del equipo con Firebase RTDB.
Tareas grupales con asignación, prioridad y estado.

Estructura en RTDB:
  team_tasks/{task_id}/
    title: str
    assigned_to: str (phone number)
    assigned_by: str (phone number)
    priority: int (1, 2, 3)
    due_date: str|None (ISO date)
    status: "pending" | "in_progress" | "done"
    category: str
    created_at: int (timestamp)
    completed_at: int|None
"""
import logging
import time
from typing import Optional

from firebase_admin import db

from bioagent.memory import _init_firebase
from bioagent.tasks import _normalize_priority, PRIORITY_EMOJI, PRIORITY_LABEL
from bioagent import team_members

logger = logging.getLogger(__name__)


def add_team_task(
    title: str,
    assigned_to: str,
    assigned_by: str,
    priority=3,
    due_date: Optional[str] = None,
    category: str = "general",
) -> Optional[str]:
    """
    Crea una tarea grupal asignada a un miembro.
    assigned_to/assigned_by: phone numbers.
    """
    if not _init_firebase():
        return None
    try:
        ref = db.reference("team_tasks")
        task = {
            "title": title,
            "assigned_to": assigned_to.replace("+", "").replace(" ", ""),
            "assigned_by": assigned_by.replace("+", "").replace(" ", ""),
            "priority": _normalize_priority(priority),
            "due_date": due_date or "",
            "status": "pending",
            "category": category,
            "created_at": int(time.time()),
        }
        result = ref.push(task)
        assigned_name = team_members.get_member_name(assigned_to)
        p_emoji = PRIORITY_EMOJI.get(task["priority"], "🟢")
        logger.info(f"✅ Tarea grupal creada {p_emoji}: '{title}' → {assigned_name} ({result.key})")
        return result.key
    except Exception as e:
        logger.error(f"❌ add_team_task error: {e}")
        return None


def get_team_tasks(only_pending: bool = True) -> list[dict]:
    """Retorna todas las tareas grupales, opcionalmente solo pendientes."""
    if not _init_firebase():
        return []
    try:
        ref = db.reference("team_tasks")
        data = ref.order_by_child("created_at").get()
        if not data:
            return []
        tasks = []
        for task_id, task_data in data.items():
            if only_pending and task_data.get("status") == "done":
                continue
            task_data["priority"] = _normalize_priority(task_data.get("priority", 3))
            tasks.append({"id": task_id, **task_data})
        tasks.sort(key=lambda t: t.get("priority", 3))
        return tasks
    except Exception as e:
        logger.error(f"❌ get_team_tasks error: {e}")
        return []


def get_tasks_for_user(user_phone: str, only_pending: bool = True) -> list[dict]:
    """Retorna las tareas grupales asignadas a un usuario específico."""
    clean = user_phone.replace("+", "").replace(" ", "")
    all_tasks = get_team_tasks(only_pending=only_pending)
    return [t for t in all_tasks if t.get("assigned_to") == clean]


def complete_team_task(task_id: str) -> bool:
    """Marca una tarea grupal como completada."""
    if not _init_firebase():
        return False
    try:
        ref = db.reference(f"team_tasks/{task_id}")
        ref.update({"status": "done", "completed_at": int(time.time())})
        logger.info(f"✅ Tarea grupal completada: {task_id}")
        return True
    except Exception as e:
        logger.error(f"❌ complete_team_task error: {e}")
        return False


def delete_team_task(task_id: str) -> bool:
    """Elimina una tarea grupal permanentemente."""
    if not _init_firebase():
        return False
    try:
        db.reference(f"team_tasks/{task_id}").delete()
        return True
    except Exception as e:
        logger.error(f"❌ delete_team_task error: {e}")
        return False


def get_team_board() -> str:
    """
    Genera el tablero de avance del equipo en formato texto.
    Muestra todas las tareas agrupadas por miembro.
    """
    tasks = get_team_tasks(only_pending=False)
    if not tasks:
        return "📊 No hay tareas grupales registradas."

    pending = [t for t in tasks if t.get("status") != "done"]
    done = [t for t in tasks if t.get("status") == "done"]

    # Agrupar pendientes por asignado
    by_member = {}
    for t in pending:
        assigned = t.get("assigned_to", "sin_asignar")
        name = team_members.get_member_name(assigned)
        if name not in by_member:
            by_member[name] = []
        by_member[name].append(t)

    lines = ["📊 *Estado del Proyecto:*\n"]

    for name, member_tasks in by_member.items():
        for t in member_tasks:
            p = t.get("priority", 3)
            emoji = PRIORITY_EMOJI.get(p, "🟢")
            status_emoji = "🔄" if t.get("status") == "in_progress" else "⏳"
            due = f" (vence {t['due_date']})" if t.get("due_date") else ""
            lines.append(f"{status_emoji} {emoji} *{name}* — {t['title']}{due}")

    if done:
        lines.append("")
        for t in done[-5:]:  # últimas 5 completadas
            name = team_members.get_member_name(t.get("assigned_to", ""))
            lines.append(f"✅ *{name}* — ~~{t['title']}~~")

    total = len(pending) + len(done)
    progress = int((len(done) / total) * 100) if total > 0 else 0
    lines.append(f"\n*Progreso: {progress}% ({len(done)}/{total} tareas listas)*")

    return "\n".join(lines)


def get_team_tasks_summary_for_user(user_phone: str) -> str:
    """Resumen de tareas grupales asignadas al usuario, para inyectar en el prompt."""
    user_tasks = get_tasks_for_user(user_phone, only_pending=True)
    if not user_tasks:
        return ""

    lines = ["## Tareas del Equipo asignadas a ti:"]
    for t in user_tasks:
        p = t.get("priority", 3)
        emoji = PRIORITY_EMOJI.get(p, "🟢")
        due = f" | Vence: {t['due_date']}" if t.get("due_date") else ""
        lines.append(f"- {emoji} {t['title']} (ID: {t['id']}){due}")

    return "\n".join(lines)
