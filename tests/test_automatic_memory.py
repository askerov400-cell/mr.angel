import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from memory import service
from memory.validation import validate


def item(kind="FACT", **fields):
    return {"type": kind, "category": "personal", "memory_text": "Synthetic fact",
            "confidence": 0.95, **fields}


class ValidationTests(unittest.TestCase):
    def test_invalid_model_output_does_not_pass(self):
        for raw in (None, [], item(confidence=float("nan")), item(confidence=0.4),
                    item(confidence=True), item(memory_text=""), item("IGNORE"),
                    item("STATE", state_key="weight", state_value=None),
                    item("STATE", state_key="invalid key", state_value=12)):
            self.assertIsNone(validate(raw))

    def test_all_supported_types_and_false_state(self):
        for kind in ("FACT", "GOAL", "EVENT", "OBSERVATION"):
            self.assertEqual(validate(item(kind))["type"], kind)
        self.assertIsNotNone(validate(item("STATE", state_key="sugar", state_value=False, state_unit=None)))

    def test_observation_is_marked_as_assumption(self):
        text = service.format_memory({"memory_entries": [{
            "memory_type": "OBSERVATION", "memory_text": "Synthetic assumption",
        }]})
        self.assertIn("предположение, не факт", text)


class ProcessingTests(unittest.IsolatedAsyncioTestCase):
    async def test_bare_numbers_never_call_model_or_write(self):
        with patch("memory_classifier.classify_memory", new=AsyncMock()) as model, \
                patch.object(service, "save_automatic") as save:
            for text in ("77", "75.5", "77 кг", " 77 ", "77%"):
                self.assertEqual(await service.process(12, text), "needs_context")
            model.assert_not_awaited()
            save.assert_not_called()

    async def test_invalid_classification_never_writes(self):
        with patch("memory_classifier.classify_memory", new=AsyncMock(return_value=[])), \
                patch.object(service, "save_automatic") as save:
            self.assertEqual(await service.process(12, "Synthetic text"), "ignored")
            save.assert_not_called()

    async def test_classifier_failure_does_not_break_conversation(self):
        with patch("memory_classifier.classify_memory", new=AsyncMock(side_effect=TimeoutError)):
            self.assertEqual(await service.process(12, "Synthetic text"), "failed")

    async def test_owner_is_from_caller_not_model(self):
        with patch("memory_classifier.classify_memory", new=AsyncMock(return_value=item(telegram_user_id=99))), \
                patch.object(service, "save_automatic", return_value=True) as save:
            self.assertEqual(await service.process(12, "Synthetic text"), "saved")
            self.assertEqual(save.call_args.args[0], 12)

    async def test_storage_failure_and_duplicate_status(self):
        with patch("memory_classifier.classify_memory", new=AsyncMock(return_value=item())):
            with patch.object(service, "save_automatic", side_effect=RuntimeError):
                self.assertEqual(await service.process(12, "Synthetic text"), "failed")
            with patch.object(service, "save_automatic", return_value=False):
                self.assertEqual(await service.process(12, "Synthetic text"), "unchanged")

    async def test_context_read_failure_has_safe_fallback(self):
        with patch.object(service, "recent_memory", side_effect=RuntimeError("private error")):
            text = await service.context(12)
            self.assertIn("недоступна", text)
            self.assertNotIn("private error", text)
