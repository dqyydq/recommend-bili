import unittest
from datetime import datetime, timedelta, timezone

from memory_service import effective_confidence, present_memory, validate_memory_state


class MemoryServiceTests(unittest.TestCase):
    def test_behavior_memory_uses_ninety_day_half_life(self) -> None:
        now = datetime.now(timezone.utc)
        memory = {
            "confidence": 0.8,
            "status": "active",
            "source_kind": "behavior",
            "memory_type": "semantic",
            "updated_at": now - timedelta(days=90),
        }
        self.assertAlmostEqual(effective_confidence(memory, now=now), 0.4, places=3)

    def test_explicit_and_procedural_memories_do_not_decay(self) -> None:
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=900)
        explicit = {"confidence": 0.9, "status": "active", "source_kind": "explicit", "memory_type": "semantic", "updated_at": old}
        procedural = {"confidence": 1, "status": "active", "source_kind": "system", "memory_type": "procedural", "updated_at": old}
        self.assertEqual(effective_confidence(explicit, now=now), 0.9)
        self.assertEqual(effective_confidence(procedural, now=now), 1)

    def test_silence_cannot_mark_inferred_interest_dormant(self) -> None:
        with self.assertRaisesRegex(ValueError, "只能来自用户明确表达"):
            validate_memory_state("behavior", "dormant")
        validate_memory_state("explicit", "dormant")

    def test_outdated_memory_has_zero_effective_confidence(self) -> None:
        memory = {"confidence": 1, "status": "outdated", "source_kind": "explicit", "memory_type": "semantic", "interest_state": "active"}
        presented = present_memory(memory)
        self.assertEqual(presented["effective_confidence"], 0)
        self.assertIn("过时", presented["state_reason"])


if __name__ == "__main__":
    unittest.main()
