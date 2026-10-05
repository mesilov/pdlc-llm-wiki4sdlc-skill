---
name: wiki-merge
description: "Use when в проекте найдены дублирующие или пересекающиеся canonical pages, документ нужно безопасно разделить, либо требуется объединение с сохранением уникального знания и входящих ссылок."
---

# Объединение и разделение страниц wiki

Merge/split должен уменьшать конкуренцию источников истины, не теряя evidence,
историю, uncertainty и inbound links. Похожее имя само по себе не доказывает
дублирование.

Перед процедурой полностью прочитай [общий контракт набора](../wiki-query/references/contract.md),
затем разрешённые `knowledge/SCHEMA.md` и `knowledge/index.md`. Применяй
профиль путей, правила подключённых интеграций и контекст целевого проекта.

## Workflow

1. Классифицируй каждый документ как canonical, supporting, historical или
   duplicate. Сравни scope, date, claims, evidence и contradictions.
2. Выбери canonical base и объясни boundary. Если документы описывают разные
   concepts, не объединяй их; при смешанном документе спроектируй split.
3. Найди inbound dependencies через `bin/wiki/affected <path>`, `rg` по
   basename/title/synonyms и прямое чтение index, decisions и подключённую спецификацию, если она используется.
4. Перенеси в canonical page всё уникальное актуальное знание, provenance,
   assumptions и unresolved conflicts. Не делай source dump. Для глоссария
   применяй [общие правила](../wiki-query/references/glossary.md): при совпадении
   понятий сохрани поддержанные синонимы и причины нежелательных названий.
   Совпадение названий без совпадения понятий не разрешает merge. Не удаляй
   сам термин из-за смешанной записи и не теряй вынесенные проектные правила.
5. Для tracked move используй `git mv`. Duplicate удаляй только после проверки
   уникального content; historical non-evidence перемещай в archive с явной
   superseding link, если он всё ещё полезен.
6. Исправь все inbound relative links, semantic index и полезные reciprocal
   links. Значимое изменение boundaries запиши в `knowledge/log.md`.
7. Обязательно выполни финальную процедуру [wiki-lint](../wiki-lint/SKILL.md)
   в режиме `fix`: сверка терминов затронутых статей с глоссарием, правки с
   provenance, сортировка и повторная проверка всей wiki. Выполни
   `bin/wiki/affected` для старых paths/titles и `bin/wiki/find-orphans`.

## Результат

Сообщи выбранный canonical base, перенесённое уникальное знание, сохранённые
conflicts/evidence, удалённые или архивированные paths, repaired links и
результаты проверок. Если canonical boundary неоднозначна, не удаляй документы
и запроси решение владельца.
