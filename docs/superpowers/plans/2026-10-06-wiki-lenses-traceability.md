# Wiki Lenses and Traceability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Закрепить семь тематических представлений и проверяемую трассировку wiki ↔ OpenSpec; сократить README примерно вдвое.

**Architecture:** Профиль задаёт каталог views и семь ключей линз. Карты `traceability.json` в канонических доменах перечисляют область проверки и связи стабильных ID. Отдельный модуль проверяет структуру графа и fingerprint ручной смысловой проверки; обычный lint вызывает его при подключённом OpenSpec.

**Tech Stack:** Python 3.10+, стандартная библиотека, Markdown, JSON, unittest.

## Согласованная область

- Семь линз: product, discovery, experience, engineering, go-to-market, operations, measurement.
- Шесть этапов PDLC: Discovery, Definition, Design, Development, Launch, Optimization; Ideation входит в Discovery.
- Validation — сквозная деятельность, а не дополнительная обязательная линза.
- `layers.views` по умолчанию равен `views`; старые каталоги не мигрируются автоматически.
- OpenSpec остаётся выключен без явного профиля. Новые зависимости не добавляются.
- Карта явно выбирает wiki-файлы и OpenSpec-файлы. Проверка не обещает охват незаявленных файлов или слияние delta с main spec.
- Стабильные ID задаются заголовками `Requirement: [ID]` и `Scenario: [ID]` в обеих сторонах.
- Каждый сценарий OpenSpec связан с родительским Requirement, требованиями и сценариями wiki.
- Карта даёт прямые и обратные связи; исключения из scope имеют причины и показаны отдельно.
- Смысловая проверка имеет status, reviewer, note и SHA-256 проверенного набора. CLI не проверяет смысл Given/When/Then.

## Task 1: Профиль и представления

- [x] Изменить ожидания default views в `tests/wiki_harness/test_profile.py`; добавить проверку `layers.views` и вложенного status.
- [x] Запустить `python3 -m unittest tests.wiki_harness.test_profile` и увидеть ошибки старого профиля.
- [x] Синхронизировать `bin/wiki/_core.py`, contract, profile, pdlc, SCHEMA и index.
- [x] Проверить явный список views, `[]`, старое расположение и отсутствие пустых страниц.

## Task 2: Проверка трассировки

- [x] Добавить CLI-тесты `tests/wiki_harness/test_trace.py` с временной wiki и независимой спецификацией.
- [x] Увидеть отказ отсутствующей команды, затем реализовать `bin/wiki/_trace.py` и `bin/wiki/trace`.
- [x] Проверить полное покрытие, лишний Scenario, непокрытый wiki Scenario, неверного родителя и повторный ID.
- [x] Проверить исключения, перенос файлов, fence-блоки, относительные пути, symlinks и профиль с другими корнями.
- [x] Проверить pending/reviewed/stale и изменение fingerprint после правки требований, решений или карты.
- [x] Добавить trace в установку и structural lint. Без карт или OpenSpec обычная wiki продолжает работать.

## Task 3: Правила и README

- [x] Добавить `references/traceability.md` с полным JSON-примером, областью проверки и критериями готовности.
- [x] Синхронизировать query/audit/lint/decide/update/merge и общие правила создания связей.
- [x] Переписать README по полному simple-russian, сохранив команды, ограничения и пути.
- [x] Выполнить полный чек-лист письма. Сравнить `wc -w README.md` с исходными 980 словами.
- [x] Повторить сценарий проверки навыков по новым правилам и записать фактический результат.

## Task 4: Приёмка

- [x] Запустить `python3 -m unittest discover -s tests -t .`.
- [x] Проверить установку и trace в отдельном временном проекте.
- [x] Выполнить независимый обзор соответствия согласованной области, затем обзор качества.
- [x] Выполнить `git diff --check` и отдельно проверить whitespace новых файлов.
- [x] Предъявить результат без утверждений о runtime или смысловой корректности продуктовой спеки.
