import unittest
from memory.dialogue_context import resolve


def question(text):
    return [{"role": "assistant", "content": text}]


class DialogueContextTests(unittest.TestCase):
    def test_explicit_weight_and_height(self):
        self.assertEqual(resolve("77", question("Какой сейчас твой вес в кг?")), "Сейчас мой вес 77 кг.")
        self.assertEqual(resolve("175", question("Какой твой рост в см?")), "Сейчас мой рост 175 см.")

    def test_ambiguous_context_is_not_used(self):
        for history in (None, [], question("Какой вес?"), question("Вес в кг."),
                        question("Какой вес в кг и рост в см?"),
                        question("Какой был твой вес вчера в кг?"),
                        question("Какой вес твоего друга в кг?"),
                        question("Какой твой вес в кг? Это точно?"),
                        [{"role": "user", "content": "Какой вес в кг?"}]):
            self.assertEqual(resolve("77", history), "77")

    def test_multiple_numbers_and_negative_value_are_not_resolved(self):
        for value in ("77 и 75", "-77", "0", "да"):
            self.assertEqual(resolve(value, question("Какой твой вес в кг?")), value)
