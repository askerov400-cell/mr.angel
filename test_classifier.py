import asyncio

from memory_manager import classify_memory


TEST_MESSAGES = [
    "У меня есть собака по кличке Ричи.",
    "Хочу за следующие 6 месяцев увеличить доход бизнеса.",
    "Сегодня я подписал договор с новым поставщиком.",
    "Как думаешь, стоит ли мне завтра поехать в офис?",
    "Привет, как дела?"
]


async def main():

    print("ТЕСТ КЛАССИФИКАТОРА ПАМЯТИ")
    print("=" * 60)

    for message in TEST_MESSAGES:

        print()
        print("СООБЩЕНИЕ:")
        print(message)

        try:
            result = await classify_memory(message)

            print()
            print("РЕШЕНИЕ:")
            print(f"Тип: {result['type']}")
            print(f"Категория: {result['category']}")
            print(f"Память: {result['memory_text']}")
            print(f"Уверенность: {result['confidence']}")
            print(f"Причина: {result['reason']}")

        except Exception as error:
            print()
            print("ОШИБКА:")
            print(error)

        print("-" * 60)


if __name__ == "__main__":
    asyncio.run(main())