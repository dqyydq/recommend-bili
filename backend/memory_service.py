import math
from datetime import datetime, timezone
from typing import Any


MEMORY_TYPES = {"semantic", "episodic", "procedural"}
INTEREST_STATES = {"active", "cooling", "dormant", "historical"}
SOURCE_KINDS = {"explicit", "behavior", "project", "system"}


def effective_confidence(memory: dict[str, Any], now: datetime | None = None) -> float:
    confidence = max(0.0, min(1.0, float(memory.get("confidence") or 0)))
    if memory.get("status") != "active":
        return 0.0
    if memory.get("source_kind") in {"explicit", "system"} or memory.get("memory_type") == "procedural":
        return confidence
    if memory.get("project_id") and memory.get("valid_until"):
        valid_until = memory["valid_until"]
        if isinstance(valid_until, str):
            valid_until = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
        if valid_until <= (now or datetime.now(timezone.utc)):
            return 0.0
    updated = memory.get("last_confirmed_at") or memory.get("updated_at") or memory.get("created_at")
    if not updated:
        return confidence
    if isinstance(updated, str):
        updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    current = now or datetime.now(timezone.utc)
    age_days = max(0.0, (current - updated).total_seconds() / 86400)
    return confidence * math.pow(0.5, age_days / 90.0)


def validate_memory_state(source_kind: str, interest_state: str) -> None:
    if source_kind not in SOURCE_KINDS:
        raise ValueError("invalid memory source")
    if interest_state not in INTEREST_STATES:
        raise ValueError("invalid interest state")
    if interest_state == "dormant" and source_kind != "explicit":
        raise ValueError("休眠兴趣只能来自用户明确表达或确认")


def validate_memory_update(memory: dict[str, Any], changes: dict[str, Any]) -> None:
    next_state = changes.get("interest_state", memory.get("interest_state", "active"))
    validate_memory_state(str(memory.get("source_kind") or "behavior"), str(next_state))
    if "confidence" in changes and not 0 <= float(changes["confidence"]) <= 1:
        raise ValueError("置信度必须在 0 到 1 之间")


def memory_reason(memory: dict[str, Any], effective: float) -> str:
    if memory.get("status") == "outdated":
        return "你已将这条记忆标记为过时"
    if memory.get("interest_state") == "dormant":
        return "来自你的明确表达或确认"
    if memory.get("source_kind") == "explicit":
        return "来自你的明确表达，不自动衰减"
    if memory.get("project_id"):
        return "仅在关联学习项目有效时参与推荐"
    if effective < float(memory.get("confidence") or 0) * 0.75:
        return "推断信号随时间按 90 天半衰期降权"
    return "近期行为证据仍然有效"


def present_memory(memory: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    effective = effective_confidence(memory, now=now)
    return {**memory, "effective_confidence": round(effective, 4), "state_reason": memory_reason(memory, effective)}
