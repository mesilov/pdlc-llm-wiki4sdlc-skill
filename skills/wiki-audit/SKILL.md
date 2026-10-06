---
name: wiki-audit
description: "Use when нужно глубоко проверить, поддержаны ли важные claims проекта источниками, достаточно ли они актуальны, противоречат ли им другие данные и корректно ли они распространились по слоям. Техническое письмо опирается на полный каталог SimpleEn-RU по разделу 8.2 ГОСТ Р 58049-2017 — стандарта перевода эксплуатационной документации авиационной техники с/на иностранные языки."
---

# Аудит утверждений проекта

Audit проверяет claim-to-evidence integrity глубже link lint: существующий
source может быть stale, ненадёжным, вне scope или не поддерживать вывод.
Приоритетны pricing, API capabilities, platform limits, competitors,
regulations, privacy, market claims и external services.

Перед процедурой полностью прочитай [общий контракт набора](../wiki-query/references/contract.md),
затем разрешённые `knowledge/SCHEMA.md` и `knowledge/index.md`. Применяй
профиль путей, правила подключённых интеграций и контекст целевого проекта.

## Workflow

1. Зафиксируй audit date и разбей compound prose на atomic claims.
2. Классифицируй claim: external fact, internal observation, hypothesis,
   implication, decision, specification или implementation assertion.
   В глоссарии проверяй определения и эквивалентность названий по
   [общим правилам](../wiki-query/references/glossary.md). Отмечай подмену
   значения проектным решением и неподдержанные синонимы; ссылка на accepted
   decision сама по себе эти проблемы не исправляет.
3. Дойди до raw source и проверь существование, смысл, version/region/plan/
   context и authority.
4. Для drift-prone claim найди более новое primary evidence; исторический
   snapshot не обновляй на месте.
5. Ищи contradictions в raw и canonical knowledge, сравнивая date, scope,
   method и reliability.
6. Проследи downstream impact через представления из схемы проекта, decisions,
   подключённую спецификацию и implementation. Проверь прямые/обратные ссылки,
   точные идентификаторы, незакрытые deferred и покрытие scope решения.
7. Запусти `bin/wiki/affected <path-or-phrase>` и `bin/wiki/lint --dry-run`.
   Если corrections входят в разрешённую задачу, заверши их обязательной
   процедурой [wiki-lint](../wiki-lint/SKILL.md) в режиме `fix`, включая сверку
   терминов, сортировку глоссария и повторную проверку всей wiki.

Используй состояния `supported`, `partially-supported`, `unsupported`, `stale`,
`contradicted`, `not-a-factual-claim`. Для finding укажи file/line, evidence,
impact, confidence и минимальную remediation.

Не редактируй disputed claim во время report-only audit. Сначала покажи evidence
и affected pages; отсутствие source не является подтверждением. Не объявляй
всю wiki проверенной по bounded scope.
