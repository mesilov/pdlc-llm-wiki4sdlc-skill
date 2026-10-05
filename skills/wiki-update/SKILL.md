---
name: wiki-update
description: "Use when существующее знание проекта нужно каскадно обновить из-за уже сохранённого evidence, уточнения, решения, спецификации или implementation observation без отдельного нового исследования."
---

# Обновление wiki проекта

Обновляй существующие concepts, а не создавай параллельную страницу. Этот skill
не собирает новые внешние источники: для них используй `wiki-ingest` или
`wiki-research`.

Перед процедурой полностью прочитай [общий контракт набора](../wiki-query/references/contract.md),
затем разрешённые `knowledge/SCHEMA.md` и `knowledge/index.md`. Применяй
профиль путей, правила подключённых интеграций и контекст целевого проекта.

## Workflow

1. Назови изменение понимания и его основание: уже сохранённый raw source,
   correction, decision, OpenSpec или dated implementation observation.
2. Запусти `bin/wiki/affected <path-or-phrase>` как начальный candidate set,
   затем дополни его semantic search по synonyms и затронутым claims.
3. Найди один canonical base. Если есть competing pages, остановись и примени
   `wiki-merge` до содержательного update.
4. Обнови canonical domain, сохраняя старое evidence и видимое противоречие.
5. Каскадно измени только те представления из схемы проекта, assumptions,
   open questions и decisions, чьи implications действительно изменились.
   Проверь затронутую трассировку решений в подключённую спецификацию
   и обратные ссылки, если интеграция используется.
   Никогда не меняй decision status молча. Для изменения значения, названия
   или синонимов применяй [общие правила глоссария](../wiki-query/references/glossary.md).
   При нормализации терминов учитывай затронутые употребления старых названий,
   сохраняй контекст и входящие ссылки; не делай глобальную замену синонимов.
6. Обнови `knowledge/index.md`, только если изменилась semantic navigation;
   значимое изменение понимания добавь в `knowledge/log.md`.
7. Обязательно выполни финальную процедуру [wiki-lint](../wiki-lint/SKILL.md)
   в режиме `fix`: сверка терминов затронутых статей с глоссарием, правки с
   provenance, сортировка и повторная проверка всей wiki. Затем повтори
   `bin/wiki/affected`; проверь provenance и уровень уверенности.

## Результат

Сообщи основание update, canonical page, все изменённые downstream pages,
неизменённые кандидаты и причину, contradictions, assumptions/questions и
результаты проверок. Не делай meaningless touches ради видимого cascade.
