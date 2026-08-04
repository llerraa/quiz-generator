"""
Клиент GigaChat API для генерации тестовых вопросов.

TODO (следующий этап разработки): реализовать обёртку над GigaChat SDK —
класс GigaChatClient с методом generate_questions(text, question_types,
count), инкапсулирующий промпт-инжиниринг и парсинг structured-ответа
в список вопросов (MCQ / true-false / matching).

Ключ и параметры уже готовы — читаются из src/config.py (Config.GIGACHAT_*),
менять здесь ничего не придётся при переходе с персонального ключа
на организационный ключ ИМЭС.
"""
