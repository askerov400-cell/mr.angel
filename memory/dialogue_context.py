"""Resolve only explicit, supported numeric follow-ups."""
import re


NUMBER = re.compile(r"\s*([+-]?\d+(?:[.,]\d+)?)\s*[.!]?\s*")


def resolve(text, history):
    match = NUMBER.fullmatch(text)
    if not match or not history:
        return text
    previous = history[-1]
    if previous.get("role") != "assistant":
        return text
    question = previous.get("content", "").lower()
    if question.count("?") != 1:
        return text
    if re.search(r"\b(?:был|была|будет|раньше|вчера|цель|хочешь|друга|подруги|ребёнка|ребенка)\b", question):
        return text
    if not re.search(r"\b(?:твой|ты|тебя)\b", question):
        return text
    weight = bool(re.search(r"\b(?:вес|весишь|весите)\b", question))
    height = bool(re.search(r"\bрост\b", question))
    if weight == height:
        return text
    value = match.group(1).replace(",", ".")
    if float(value) <= 0:
        return text
    if weight and re.search(r"\b(?:кг|килограммах)\b", question):
        return f"Сейчас мой вес {value} кг."
    if height and re.search(r"\b(?:см|сантиметрах)\b", question):
        return f"Сейчас мой рост {value} см."
    return text
