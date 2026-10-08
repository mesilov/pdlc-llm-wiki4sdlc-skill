# PDLC LLM Wiki Skills

Восемь `wiki-*` работают с wiki в Git: сохраняют источники, обобщают знания,
записывают решения и связывают требования со сценариями OpenSpec.
Набор сохраняет происхождение, противоречия и неизвестные.
Факт, гипотеза, решение, спецификация, реализация и наблюдение в runtime имеют разные основания.
Правила принятия решений, Git, CI и публикации задаёт целевой проект.

| Skill | Задача | Запись |
| --- | --- | --- |
| [wiki-query](skills/wiki-query/SKILL.md) | Ответ по знаниям | Нет |
| [wiki-ingest](skills/wiki-ingest/SKILL.md) | Обработка нового источника | Да |
| [wiki-research](skills/wiki-research/SKILL.md) | Исследование вопроса | Да |
| [wiki-update](skills/wiki-update/SKILL.md) | Обновление по имеющимся основаниям | Да |
| [wiki-decide](skills/wiki-decide/SKILL.md) | Предложение или запись решения | Да |
| [wiki-audit](skills/wiki-audit/SKILL.md) | Проверка оснований и свежести | По разрешению |
| [wiki-merge](skills/wiki-merge/SKILL.md) | Объединение или разделение страниц | Да |
| [wiki-lint](skills/wiki-lint/SKILL.md) | Проверка структуры и смысла | Только fix |

Query, report-only audit и dry-run lint ничего не записывают.
Запись разрешена в пределах запроса; она не разрешает commit или публикацию.
Ingest начинается с источника, research — с вопроса и поиска источников.

## Организация знаний

[Семь тематических линз](skills/wiki-query/references/pdlc.md) охватывают вопросы PDLC и SDLC:
`product`, `discovery`, `experience`, `engineering`, `go-to-market`, `operations`, `measurement`.
Представления живут в `knowledge/views/<lens>/` и опираются на канонические страницы `domains`.
Линзы не задают статусы или обязательную последовательность работ.
Каталоги появляются по содержимому; существующая wiki сохраняет свою структуру.
PDLC содержит шесть этапов, а Validation проходит через все этапы.

## Используемые подходы

| Подход | Применение в наборе |
| --- | --- |
| Wiki в Git | Первичные материалы, канонические знания, решения, история и относительные ссылки |
| Тематические линзы PDLC и SDLC | [Представления](skills/wiki-query/references/pdlc.md) по вопросам; этапы цикла описываются отдельно |
| Domain modeling / glossary | Одно каноническое название и `_Avoid_` с причиной; [происхождение адаптации](docs/provenance.md#глоссарий-и-синонимы--2026-10-05) |
| SimpleEn-RU / УТР | [Полный исходный навык и границы применения](skills/wiki-query/references/writing.md) для технического текста |
| Явная трассировка wiki ↔ OpenSpec | [Карты требований и сценариев](skills/wiki-query/references/traceability.md) при подключении проекта |
| Open Knowledge Format (OKF) v0.2 | [Необязательные метаданные](skills/wiki-query/references/metadata.md): источники, содержательные правки, проверки и срок перепроверки |

Идеи OKF применяются в инструкциях агента. CLI пока не разбирает YAML-метаданные;
экспорт в OKF и автоматический граф не реализованы.
Набор не требует миграции существующего корпуса, нового сервиса или изменения профиля.
См. [источник OKF и границы заимствования](docs/provenance.md#метаданные-из-okf--2026-10-09).

## Установка

Нужен Python 3.10+. CLI использует стандартную библиотеку; OpenSpec необязателен.
Для исследования нужен доступ к источникам; иначе агент сообщает ограничение.

Создайте каталог целевого проекта. В checkout набора запустите предварительную проверку:

```bash
python3 scripts/install.py /path/to/project --init-wiki --dry-run
```

Установите комплект и новую wiki:

```bash
python3 scripts/install.py /path/to/project --init-wiki
```

Для существующей wiki установите комплект без `--init-wiki`:

```bash
python3 scripts/install.py /path/to/project
```

Скрипт копирует skills в `.agents/skills/`, CLI — в `bin/wiki/`.
`--init-wiki` добавляет нейтральный корпус и `wiki.config.json`; `--claude` добавляет aliases.
Скрипт отклоняет отличающиеся файлы и symlinks до записи; одинаковые файлы пропускает.
AGENTS.md и CI проекта скрипт не меняет.

Сравните локальные изменения перед переносом.

Настройте [профиль](skills/wiki-query/references/profile.md): имя, контекст, язык, пути, документы, слои, views, решения и глоссарий.
Устанавливайте восемь skills вместе: они используют [общий контракт](skills/wiki-query/references/contract.md).

OpenSpec выключен: `openspec_root: null`.

Для существующей интеграции укажите её путь.

## Проверки

Из корня целевого проекта запустите команды:

```bash
bin/wiki/lint --dry-run
bin/wiki/status
bin/wiki/find-orphans
bin/wiki/affected 'понятие или путь'
```

При подключении OpenSpec запустите трассировку:

```bash
bin/wiki/trace --json --require-reviewed
```

[Trace](skills/wiki-query/references/traceability.md) проверяет карты wiki ↔ OpenSpec до отдельных сценариев.
Ручной статус `reviewed` и review fingerprint не подтверждают реализацию или runtime.
CLI проверяет структуру; смысл проверяет агент.

Affected показывает кандидатов; агент проверяет полноту влияния.
`bin/wiki/lint --fix` сортирует H2-блоки глоссария в разрешённом scope.
Fix не заменяет смысловую проверку и не меняет решения.
Коды lint: 0 — без ошибок, 1 — ошибки, 2 — неверный вызов или профиль.
Warnings не меняют код.

Навыки используют полный [simple-russian](skills/wiki-query/references/utr-source/skills/simple-russian/SKILL.source.md), чек-лист и примеры.
[Writing](skills/wiki-query/references/writing.md) объясняет режимы, происхождение и границы применения.
Это вспомогательный пересказ ГОСТ Р 58049-2017; CLI не подтверждает соответствие стандарту.

В репозитории набора запустите тесты:

```bash
python3 -m unittest discover -s tests -t .
```

Установку проверяют на временном проекте.
См. [происхождение](docs/provenance.md) и [проверку навыков](docs/skill-validation.md).
