import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

BASE_DIR = Path(__file__).resolve().parent.parent / "data" / "classifications"


def _user_dir(uid: str) -> Path:
    if not uid.isdigit():
        raise ValueError("invalid user id")
    path = (BASE_DIR / uid).resolve()
    if BASE_DIR.resolve() not in path.parents:
        raise ValueError("invalid storage path")
    path.mkdir(parents=True, exist_ok=True)
    return path


def save(uid: str, data: dict) -> str:
    user_dir = _user_dir(uid)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"{ts}_{uuid4().hex[:8]}.json"
    payload = {
        "created_at": datetime.now().isoformat(),
        "folder_name": data.get("folder_name", "全部收藏夹"),
        "total": data.get("total", 0),
        "categories": data.get("categories", []),
    }
    with (user_dir / filename).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return filename


def list_history(uid: str) -> list[dict]:
    user_dir = _user_dir(uid)
    result = []
    for path in sorted(user_dir.glob("*.json"), reverse=True):
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            result.append({
                "filename": path.name,
                "created_at": data.get("created_at", ""),
                "total": data.get("total", 0),
                "categories_count": len(data.get("categories", [])),
            })
        except (OSError, json.JSONDecodeError):
            continue
    return result


def load(uid: str, filename: str) -> dict | None:
    if Path(filename).name != filename or not filename.endswith(".json"):
        return None
    user_dir = _user_dir(uid)
    path = (user_dir / filename).resolve()
    if path.parent != user_dir or not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
