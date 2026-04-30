"""
BioAgent — Briefing Matutino.
Genera el resumen personalizado del día para cada usuario a las 8:00 AM.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from bioagent import (
    calendar_service, tasks, lists, habits, team_tasks, team_members, memory
)

logger = logging.getLogger(__name__)


async def generate_briefing(user_phone: str) -> str:
    """
    Genera el briefing matutino personalizado para un usuario.
    Incluye: agenda del día, tareas urgentes, tareas del equipo, hábitos, listas.
    """
    member_name = team_members.get_member_name(user_phone)
    now_local = datetime.now(timezone.utc) - timedelta(hours=5)
    today_str = now_local.strftime("%A %d de %B")  # ej: "miércoles 30 de abril"

    parts = [f"🌅 *Buenos días, {member_name}!*\n📆 {today_str}\n"]

    # 1. Agenda personal del día
    agenda = await calendar_service.get_user_agenda_summary_async(user_phone, days=1)
    if agenda and "No hay eventos" not in agenda:
        parts.append(agenda)
    else:
        parts.append("📅 No tienes eventos hoy.")

    # 2. Tareas personales urgentes/importantes
    user_tasks = await asyncio.to_thread(tasks.get_tasks, user_phone, True)
    urgent = [t for t in user_tasks if t.get("priority", 3) in (1, 2)]
    if urgent:
        parts.append("\n📋 *Tareas importantes:*")
        for t in urgent[:5]:
            p_emoji = tasks.PRIORITY_EMOJI.get(t["priority"], "🟢")
            due = f" (vence {t['due_date']})" if t.get("due_date") else ""
            parts.append(f"{p_emoji} {t['title']}{due}")
    
    # Contar tareas normales sin mostrarlas
    normal_count = len(user_tasks) - len(urgent)
    if normal_count > 0:
        parts.append(f"🟢 + {normal_count} tareas más.")

    # 3. Tareas del equipo asignadas a este usuario
    team_user_tasks = await asyncio.to_thread(
        team_tasks.get_tasks_for_user, user_phone, True
    )
    if team_user_tasks:
        parts.append(f"\n🏢 *Tareas del equipo ({len(team_user_tasks)}):*")
        for t in team_user_tasks[:3]:
            p_emoji = tasks.PRIORITY_EMOJI.get(t.get("priority", 3), "🟢")
            due = f" (vence {t['due_date']})" if t.get("due_date") else ""
            parts.append(f"{p_emoji} {t['title']}{due}")
        if len(team_user_tasks) > 3:
            parts.append(f"... y {len(team_user_tasks) - 3} más.")

    # 4. Hábitos pendientes de ayer (si no registró)
    yesterday = (now_local - timedelta(days=1)).strftime("%Y-%m-%d")
    active_habits = await asyncio.to_thread(habits.get_habits, user_phone)
    if active_habits:
        yesterday_logs = await asyncio.to_thread(habits.get_habit_logs, user_phone, yesterday)
        unlogged = [h for h in active_habits if h["id"] not in yesterday_logs]
        if unlogged:
            parts.append(f"\n⚠️ Ayer no registraste: {', '.join(h['name'] for h in unlogged)}")

    # 5. Listas con pendientes
    all_lists = await asyncio.to_thread(lists.get_all_lists, user_phone)
    if all_lists:
        list_summary = ", ".join(
            f"{cat.replace('_', ' ')} ({len(items)})" for cat, items in all_lists.items()
        )
        parts.append(f"\n🛒 Listas pendientes: {list_summary}")

    # 6. Cierre motivacional
    parts.append("\n💪 ¡A darle con todo! Escríbeme si necesitas algo.")

    return "\n".join(parts)


async def generate_night_checkin(user_phone: str) -> str:
    """
    Genera el check-in nocturno para un usuario.
    Pregunta por hábitos del día y tareas pendientes.
    """
    member_name = team_members.get_member_name(user_phone)
    now_local = datetime.now(timezone.utc) - timedelta(hours=5)
    today_str = now_local.strftime("%Y-%m-%d")

    parts = [f"🌙 *Check-in Nocturno, {member_name}:*"]

    # 1. Hábitos del día
    active_habits = await asyncio.to_thread(habits.get_habits, user_phone)
    if active_habits:
        today_logs = await asyncio.to_thread(habits.get_habit_logs, user_phone, today_str)
        unlogged = [h for h in active_habits if h["id"] not in today_logs]
        if unlogged:
            parts.append("\nRegistra tus hábitos de hoy. Responde indicando cuáles cumpliste:")
            for i, h in enumerate(unlogged, 1):
                parts.append(f"{i}. {h['name']}")
        else:
            parts.append("\n✅ Ya registraste todos tus hábitos de hoy.")

    # 2. Tareas pendientes del día
    pending = await asyncio.to_thread(tasks.get_tasks, user_phone, True)
    urgent_today = [t for t in pending if t.get("priority", 3) == 1]
    if urgent_today:
        parts.append(f"\n⚠️ Tienes {len(urgent_today)} tarea(s) urgente(s) sin completar:")
        for t in urgent_today[:3]:
            parts.append(f"🔴 {t['title']}")

    if not active_habits and not urgent_today:
        parts.append("\n¡Todo limpio por hoy! Descansa bien. 😴")

    parts.append("\n_Responde para renovar tu ventana de 24h._")

    return "\n".join(parts)
