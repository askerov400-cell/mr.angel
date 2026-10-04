import os
import json
import math

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not DEEPSEEK_API_KEY:
    raise RuntimeError("Не найден DEEPSEEK_API_KEY в файле .env")

client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)


SYSTEM_PROMPT = """
Ты — модуль памяти персонального ИИ-агента Хранитель.

Твоя задача — определить, нужно ли сохранять сообщение пользователя
и к какому типу памяти оно относится.

Разрешены типы:

FACT — устойчивый факт о пользователе, который обычно не меняется часто.
GOAL — цель, намерение или желаемый результат пользователя.
EVENT — значимое произошедшее событие, действие или принятое решение.
STATE — текущее изменяемое состояние пользователя.
OBSERVATION — вывод, гипотеза или закономерность агента, а не подтвержденный факт.
IGNORE — сообщение не нужно сохранять.

ВАЖНЫЕ ПРАВИЛА:

Ты получаешь только текущее сообщение, без предыдущих реплик. Не додумывай контекст.
Голые числа, число с единицей без названия показателя, ответы «да», «нет», «столько же»
и другие неоднозначные короткие ответы — IGNORE. Не превращай «77» в вес или возраст.
Не добавляй единицы измерения и сведения, которых нет в сообщении.

1. Не каждое сообщение должно становиться памятью.

2. Вопросы, приветствия, случайные фразы и обычный разговор обычно IGNORE.

3. FACT используй только для относительно устойчивой информации.
Примеры:
"У меня трое детей."
"Я родился в 1985 году."
"Мой бизнес занимается продажей стеллажей."

4. STATE используй для информации, которая описывает текущее состояние
и со временем может измениться.

Примеры:
"Сейчас я вешу 77 кг."
"Сейчас я не ем добавленный сахар."
"Сегодня у меня болит локоть."
"Сейчас я работаю над проектом Хранитель."
"Сейчас мой вес 75 кг."

Если в сообщении есть слова или смысл:
"сейчас", "сегодня", "на данный момент", "в настоящее время",
или информация по своей природе является изменяемым показателем,
предпочитай STATE, а не FACT.

5. Для STATE обязательно сформируй:

state_key — короткий стабильный технический ключ на английском языке
в snake_case.

state_value — текущее значение состояния.
Это может быть число, строка, boolean или другое простое значение.

state_unit — единица измерения, если она есть, иначе null.

Одинаковые состояния должны всегда получать одинаковый state_key.

Примеры:

"Сейчас я вешу 77 кг."
state_key: "weight"
state_value: 77
state_unit: "kg"

"Сейчас мой вес 75 кг."
state_key: "weight"
state_value: 75
state_unit: "kg"

"Сейчас я не ем добавленный сахар."
state_key: "added_sugar_consumption"
state_value: false
state_unit: null

"Я снова ем добавленный сахар."
state_key: "added_sugar_consumption"
state_value: true
state_unit: null

6. GOAL используй для целей пользователя.

7. EVENT используй для значимых событий, действий и решений,
которые уже произошли.

8. OBSERVATION нельзя выдавать за FACT.
OBSERVATION — предположение, вывод или закономерность,
которую обнаружил агент.

9. memory_text должен быть короткой самостоятельной записью,
понятной даже без исходного сообщения.

10. Не придумывай информацию, которой нет в сообщении.

11. confidence — число от 0 до 1.

12. Если type не STATE:
state_key должен быть null,
state_value должен быть null,
state_unit должен быть null.

Верни ТОЛЬКО JSON без markdown и без дополнительного текста:

{
  "type": "FACT|GOAL|EVENT|STATE|OBSERVATION|IGNORE",
  "category": "personal|family|business|finance|health|work|learning|other",
  "memory_text": "текст для памяти",
  "state_key": null,
  "state_value": null,
  "state_unit": null,
  "confidence": 0.0,
  "reason": "краткая причина"
}
"""


async def classify_memory(text: str) -> dict:
    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": text
            }
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    raw = (response.choices[0].message.content or "").strip()

    if raw.startswith("```"):
        raw = raw.replace("```json", "")
        raw = raw.replace("```", "")
        raw = raw.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "type": "IGNORE",
            "category": "other",
            "memory_text": "",
            "state_key": None,
            "state_value": None,
            "state_unit": None,
            "confidence": 0.0,
            "reason": "Не удалось разобрать ответ классификатора"
        }

    if not isinstance(result, dict):
        return {"type": "IGNORE"}

    memory_type = str(
        result.get("type", "IGNORE")
    ).upper()

    allowed_types = {
        "FACT",
        "GOAL",
        "EVENT",
        "STATE",
        "OBSERVATION",
        "IGNORE"
    }

    if memory_type not in allowed_types:
        memory_type = "IGNORE"

    confidence = result.get("confidence", 0)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence):
        confidence = 0.0

    confidence = max(
        0.0,
        min(1.0, confidence)
    )

    if memory_type == "STATE":
        state_key = result.get("state_key")
        state_value = result.get("state_value")
        state_unit = result.get("state_unit")

        if state_key is not None:
            state_key = str(state_key).strip()

        if state_unit is not None:
            state_unit = str(state_unit).strip()

    else:
        state_key = None
        state_value = None
        state_unit = None

    return {
        "type": memory_type,
        "category": str(
            result.get("category", "other")
        ),
        "memory_text": result.get("memory_text", "").strip() if isinstance(result.get("memory_text"), str) else "",
        "state_key": state_key,
        "state_value": state_value,
        "state_unit": state_unit,
        "confidence": confidence,
        "reason": str(
            result.get("reason", "")
        ).strip()
    }
