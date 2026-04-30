"""
BioAgent — Módulo de Listas (separado de Tareas).
Maneja listas simples como: compras, hogar, farmacia, etc.
Cada ítem es un string con un estado checked/unchecked.

Estructura en RTDB:
  users/{user_id}/lists/{category}/items/{item_id}/
    name: str
    checked: bool
    added_at: int (timestamp)
"""
import logging
import time
from typing import Optional

from firebase_admin import db

from bioagent.memory import _init_firebase

logger = logging.getLogger(__name__)


def add_item(user_id: str, category: str, name: str) -> Optional[str]:
    """
    Agrega un ítem a una lista. Crea la lista si no existe.
    Retorna el item_id o None si falla.
    """
    if not _init_firebase():
        return None
    try:
        cat_key = category.lower().strip().replace(" ", "_")
        ref = db.reference(f"users/{user_id}/lists/{cat_key}/items")
        item = {
            "name": name,
            "checked": False,
            "added_at": int(time.time()),
        }
        result = ref.push(item)
        logger.info(f"✅ Ítem agregado a [{cat_key}]: {name} ({result.key})")
        return result.key
    except Exception as e:
        logger.error(f"❌ add_item error: {e}")
        return None


def check_item(user_id: str, category: str, item_id: str) -> bool:
    """Marca un ítem como tachado/comprado."""
    if not _init_firebase():
        return False
    try:
        cat_key = category.lower().strip().replace(" ", "_")
        ref = db.reference(f"users/{user_id}/lists/{cat_key}/items/{item_id}")
        ref.update({"checked": True})
        logger.info(f"✅ Ítem tachado: {item_id}")
        return True
    except Exception as e:
        logger.error(f"❌ check_item error: {e}")
        return False


def uncheck_item(user_id: str, category: str, item_id: str) -> bool:
    """Desmarca un ítem."""
    if not _init_firebase():
        return False
    try:
        cat_key = category.lower().strip().replace(" ", "_")
        ref = db.reference(f"users/{user_id}/lists/{cat_key}/items/{item_id}")
        ref.update({"checked": False})
        return True
    except Exception as e:
        logger.error(f"❌ uncheck_item error: {e}")
        return False


def remove_item(user_id: str, category: str, item_id: str) -> bool:
    """Elimina un ítem de una lista permanentemente."""
    if not _init_firebase():
        return False
    try:
        cat_key = category.lower().strip().replace(" ", "_")
        db.reference(f"users/{user_id}/lists/{cat_key}/items/{item_id}").delete()
        logger.info(f"✅ Ítem eliminado: {item_id}")
        return True
    except Exception as e:
        logger.error(f"❌ remove_item error: {e}")
        return False


def get_list(user_id: str, category: str, include_checked: bool = False) -> list[dict]:
    """
    Retorna los ítems de una lista específica.
    Por defecto solo muestra los no tachados.
    """
    if not _init_firebase():
        return []
    try:
        cat_key = category.lower().strip().replace(" ", "_")
        ref = db.reference(f"users/{user_id}/lists/{cat_key}/items")
        data = ref.get()
        if not data:
            return []
        items = []
        for item_id, item_data in data.items():
            if not include_checked and item_data.get("checked", False):
                continue
            items.append({"id": item_id, **item_data})
        items.sort(key=lambda x: x.get("added_at", 0))
        return items
    except Exception as e:
        logger.error(f"❌ get_list error: {e}")
        return []


def get_all_lists(user_id: str) -> dict[str, list[dict]]:
    """
    Retorna todas las listas del usuario con sus ítems pendientes.
    Retorna: {"compras": [...], "hogar": [...], ...}
    """
    if not _init_firebase():
        return {}
    try:
        ref = db.reference(f"users/{user_id}/lists")
        data = ref.get()
        if not data:
            return {}
        result = {}
        for cat_key, cat_data in data.items():
            items_data = cat_data.get("items", {})
            items = []
            for item_id, item_data in items_data.items():
                if not item_data.get("checked", False):
                    items.append({"id": item_id, **item_data})
            if items:
                items.sort(key=lambda x: x.get("added_at", 0))
                result[cat_key] = items
        return result
    except Exception as e:
        logger.error(f"❌ get_all_lists error: {e}")
        return {}


def clear_checked(user_id: str, category: str) -> int:
    """Elimina todos los ítems tachados de una lista. Retorna cantidad eliminada."""
    if not _init_firebase():
        return 0
    try:
        cat_key = category.lower().strip().replace(" ", "_")
        ref = db.reference(f"users/{user_id}/lists/{cat_key}/items")
        data = ref.get()
        if not data:
            return 0
        count = 0
        for item_id, item_data in data.items():
            if item_data.get("checked", False):
                ref.child(item_id).delete()
                count += 1
        return count
    except Exception as e:
        logger.error(f"❌ clear_checked error: {e}")
        return 0


def get_lists_summary(user_id: str) -> str:
    """Resumen de listas para inyectar en el prompt del LLM."""
    all_lists = get_all_lists(user_id)
    if not all_lists:
        return ""

    lines = ["## Listas del Usuario:"]
    for cat, items in all_lists.items():
        cat_display = cat.upper().replace("_", " ")
        lines.append(f"\n### Lista: {cat_display}")
        for item in items[:20]:
            item_id = item.get("id", "")
            name = item.get("name", "")
            lines.append(f"- {name} (ID: {item_id})")
        if len(items) > 20:
            lines.append(f"- ... y {len(items)-20} ítems más.")

    return "\n".join(lines)
