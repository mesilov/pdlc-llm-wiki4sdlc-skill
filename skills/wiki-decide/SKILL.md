---
name: wiki-decide
description: "Use when проект должен выбрать между существенными продуктовыми, sales, архитектурными или операционными альтернативами и сохранить reasoning отдельным decision record."
---

# Решение для проекта

Переводи текущее знание в осознанный выбор. `proposed` decision уже является
полезной памятью, но не означает stakeholder acceptance.

Перед процедурой полностью прочитай [общий контракт набора](../wiki-query/references/contract.md),
затем разрешённые `knowledge/SCHEMA.md` и `knowledge/index.md`. Применяй
профиль путей, правила подключённых интеграций и контекст целевого проекта.

## Decision gate

1. Найди существующее или superseding решение по topic и synonyms.
2. Зафиксируй owner/authority, scope, deadline, success criteria и constraints.
   Срочность не превращает assumption в evidence.
3. Сравни viable alternatives, включая status quo: benefit, cost, risk,
   reversibility, dependencies и evidence gaps.
4. Выбери status по схеме проекта. Дефолтные значения:
   - `proposed` — требуется validation или принятие;
   - `accepted` — полномочный выбор активен с записанным риском;
   - `rejected` — вариант рассмотрен и не выбран;
   - `superseded` — заменён с явной ссылкой на новое решение.
5. Создай или обнови
   запись в разрешённом decisions по naming convention проекта
   (дефолт `YYYY-MM-short-decision-name.md`): context, knowledge,
   evidence, decision, why, alternatives, consequences, validation/review
   conditions, open questions и superseding links.
6. Для подключённого OpenSpec добавь трассировку по общему контракту: linked с requirement и
   обратной ссылкой, deferred с owner/условием или обоснованный not-applicable.
   Проверь полноту всех самостоятельных продуктовых следствий решения.
   Без OpenSpec используй принятую в проекте спецификацию или явно запиши,
   что поведение пока не формализовано. Это не блокирует запись proposed.
7. Обнови views только при реальном изменении implications, пересмотри
   assumptions, semantic index и `knowledge/log.md`. Уточнения терминов
   сохраняй по [общим правилам глоссария](../wiki-query/references/glossary.md);
   лимиты, правила и статус выбора остаются в decision и связанных страницах.
8. Обязательно выполни финальную процедуру [wiki-lint](../wiki-lint/SKILL.md)
   в режиме `fix`: сверка терминов затронутых страниц с глоссарием, правки с
   provenance, сортировка и повторная проверка всей wiki.

Decision не нужен для тривиальной детали из кода. Принятый выбор поведения
прослеживается до принятой в проекте спецификации; отложенная формализация
остаётся явным gap. Выполнение wiki workflow само по себе не разрешает
реализацию system change.

## Результат

Сообщи status, owner/authority, alternatives, evidence strength, consequences,
validation gate, affected pages и состояние формализации поведения. Недостаток evidence
остается bounded unknown.
