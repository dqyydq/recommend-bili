import json
import os
import tempfile
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

ENCRYPTION_KEY = os.getenv("APP_ENCRYPTION_KEY", "").strip()


def persistence_enabled() -> bool:
    return bool(ENCRYPTION_KEY)


def _fernet() -> Fernet:
    if not ENCRYPTION_KEY:
        raise RuntimeError("APP_ENCRYPTION_KEY is required for persistent secrets")
    try:
        return Fernet(ENCRYPTION_KEY.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError("APP_ENCRYPTION_KEY must be a valid Fernet key") from exc


def load_encrypted_json(path: str) -> Any | None:
    target = Path(path)
    if not target.is_file():
        return None
    try:
        raw = target.read_bytes()
        return json.loads(_fernet().decrypt(raw).decode("utf-8"))
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        print(f"[security] unable to read encrypted data: {exc}")
        return None


def save_encrypted_json(path: str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encrypted = _fernet().encrypt(payload)

    fd, temp_path = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encrypted)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
