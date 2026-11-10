# Плагин Moodle `local_qbankremotemanager` (версия ИМЭС)

Приложение создаёт тест в курсе и загружает вопросы через этот плагин. Здесь лежит его **изменённая версия
`1.2.0-imes2`** (`version` 2025031315), чтобы код не терялся по чатам.

| Что | Где |
|---|---|
| Код плагина (папку целиком ставить в `local/qbankremotemanager`) | [`qbankremotemanager/`](qbankremotemanager/) |
| Что изменено в imes1 и imes2, зачем и как проверить | [`CHANGES.md`](CHANGES.md) |
| Патчи: оригинал → imes1 → imes2 | [`patches/`](patches/) |

## Происхождение и лицензия

Оригинал: `local_qbankremotemanager` 1.2.0 (автор Peter Vanát, дипломная работа в TUKE, Кошице), **GPL v3 или новее**.
Изменения в коде помечены комментарием `Local patch`. Папка `qbankremotemanager/` остаётся под GPL v3; это не
касается остального репозитория.

## Сборка zip для установки

Moodle ждёт в архиве папку `qbankremotemanager` в корне:

```
cd moodle-plugin
zip -r ../local_qbankremotemanager_imes2.zip qbankremotemanager -x "*.DS_Store"
```

Установка: «Администрирование → Плагины → Установка плагинов» либо заменить папку `local/qbankremotemanager`.
**Плагин не удалять:** при удалении слетают функции в внешней службе. После замены: «Уведомления» → обновить,
очистить кеши. Подробнее: [`CHANGES.md`](CHANGES.md) и [README проекта](../README.md#moodle).

## Версии

| `version` | `release` | Что |
|---|---|---|
| 2025031310 | 1.2.0 | оригинал |
| 2025031311 | 1.2.0-imes1 | `supervisedmode`, `lessontypeid` |
| **2025031315** | **1.2.0-imes2** | `cmidnumber` (идентификационный номер теста). Без изменения формул журнала |

Сборки 2025031313 и 2025031314 содержали параметр `appendtogradecalc` (правка формулы журнала) и не
используются: заменяйте их на 2025031315.
