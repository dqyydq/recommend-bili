import json
import os
from datetime import datetime

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "classifications")


def _ensure_dir():
    os.makedirs(BASE_DIR, exist_ok=True)


def save(data: dict) -> str:
    _ensure_dir()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"{ts}.json"
    payload = {
        "created_at": datetime.now().isoformat(),
        "folder_name": data.get("folder_name", "全部收藏夹"),
        "total": data.get("total", 0),
        "categories": data.get("categories", []),
    }
    path = os.path.join(BASE_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return filename


def list_history() -> list[dict]:
    if not os.path.isdir(BASE_DIR):
        return []
    files = sorted(os.listdir(BASE_DIR), reverse=True)
    result = []
    for fn in files:
        if not fn.endswith(".json"):
            continue
        path = os.path.join(BASE_DIR, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            result.append({
                "filename": fn,
                "created_at": d.get("created_at", ""),
                "total": d.get("total", 0),
                "categories_count": len(d.get("categories", [])),
            })
        except Exception:
            continue
    return result


def load(filename: str) -> dict | None:
    if ".." in filename or "/" in filename:
        return None
    path = os.path.join(BASE_DIR, filename)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
