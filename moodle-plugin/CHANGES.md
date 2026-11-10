# local_qbankremotemanager: правки в версиях imes1 и imes2

Оригинал: `local_qbankremotemanager` 1.2.0 (`version` 2025031310), автор Peter Vanát, GPL v3.
Правки локальные, в код помечены комментарием `Local patch`. Новых функций веб-службы и изменений
базы данных нет, поэтому плагин обновляется «на месте» повышением `version` (удалять не нужно:
при удалении слетают функции в внешней службе).

## Сводка

| Версия | `version` | `release` | Что добавлено |
|---|---|---|---|
| оригинал | 2025031310 | 1.2.0 | — |
| imes1 | 2025031311 | 1.2.0-imes1 | `supervisedmode`, `lessontypeid` в `config` теста |
| imes2 (итоговая) | 2025031315 | 1.2.0-imes2 | `cmidnumber` в `config`, проверка уникальности номера, пояснение «кто держит номер» |

Файлы, которые менялись (одни и те же в обеих версиях):
`classes/external/qbankremotemanager_external.php`, `lang/en/local_qbankremotemanager.php`, `version.php`.

## imes1 (2025031311): поля для quizaccess_supervisedcheck

Зачем: сторонний плагин правила доступа `quizaccess_supervisedcheck` при создании теста вставляет строку в свою
таблицу и падает, если его поля пришли как NULL. Без этих полей создание теста через `upload_quiz` падало.

1. В `config` функции `local_qbankremotemanager_upload_quiz` добавлены два необязательных параметра:
   - `supervisedmode` (INT, по умолчанию 0),
   - `lessontypeid` (INT, по умолчанию -1).
2. В `$moduleinfo` (после `seb_requiresafeexambrowser`) подставляются
   `supervisedmode = (int)($config['supervisedmode'] ?? 0)` и `lessontypeid = (int)($config['lessontypeid'] ?? -1)`.
3. Две языковые строки: `supervisedmode_desc`, `lessontypeid_desc`.
4. `version.php`: `version` 2025031310 → 2025031311, `release` 1.2.0 → 1.2.0-imes1.

Если `quizaccess_supervisedcheck` не установлен, значения игнорируются.

## imes2 (2025031315): идентификационный номер теста

Зачем: на номер (`ПА-тест`) ссылаются формулы категорий журнала. Раньше плагин всегда ставил пустой `cmidnumber`.

1. В `config` добавлен необязательный параметр `cmidnumber` (PARAM_TEXT).
2. Вместо `$moduleinfo->cmidnumber = ""` номер берётся из `config`, очищается (`clean_param`, `trim`)
   и проверяется до создания теста через `grade_verify_idnumber()`. Если номер занят в курсе, возвращается
   исключение `cmidnumber_taken`, ничего не создаётся.
3. Новая приватная функция `describe_idnumber_holders()`: в тексте ошибки перечисляет, кто держит номер
   (запись `course_modules` с признаком `deletioninprogress` и/или элемент `grade_items`). Нужна потому, что
   экран журнала скрывает элементы удаляемых модулей, и причина отказа иначе не видна.
4. Две языковые строки: `cmidnumber_desc`, `cmidnumber_taken`.
5. `version.php`: `version` → 2025031315, `release` → 1.2.0-imes2.

Пустой `cmidnumber` или его отсутствие: поведение как в imes1.

### Формулы журнала НЕ меняются

Промежуточные сборки imes2 (`version` 2025031313 и 2025031314) содержали параметр `appendtogradecalc` и функцию
`append_to_category_calculation()`, которая дописывала `+[[номер]]` к формуле категории. По решению с ИМЭС
формулу менеджеры правят вручную, поэтому из итоговой сборки (2025031315) параметр и функция удалены.
Проверка: в итоговом коде нет строк `appendtogradecalc` и `append_to_category_calculation`.
Если на тестовой ЭИОС стоит сборка 2025031313 или 2025031314, её нужно заменить на 2025031315.

## Проверки

- Синтаксис PHP (`php -l`) всех файлов плагина: без ошибок.
- На тестовой ЭИОС (m45) стоит плагин imes2; какая именно сборка (2025031313, 2025031314 или 2025031315),
  надо проверить по версии в «Администрирование → Плагины → Обзор плагинов». Итоговую 2025031315 нужно поставить
  и проверить созданием теста с номером `ПА-тест` до боевой ЭИОС.

## Файлы рядом

- `qbankremotemanager_original_to_imes1.patch`: оригинал → imes1.
- `qbankremotemanager_imes1_to_imes2.patch`: imes1 → итоговая imes2.
Применение: `patch -p1 < файл.patch` из папки, где лежит каталог `qbankremotemanager` (внутри патчей пути `a/` и `b/`).
