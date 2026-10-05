# Происхождение набора

Дата выделения: 2026-10-05.

Источник: локальный репозиторий wiki-харнеса,
HEAD `2e5844a938e565a99958af4038337f06f2466193`.
В момент копирования выбранные файлы не имели незакоммиченных правок.
Изменения других файлов исходного checkout не переносились.

Перенесены восемь `.agents/skills/wiki-*/SKILL.md`,
`wiki-query/references/contract.md`, `bin/wiki/{_core.py,lint,status,find-orphans,affected}`
и независимые `tests/wiki_harness/{test_cli.py,test_glossary.py,test_profile.py}`.
Копирование не включает исходный корпус знаний, AGENTS.md, `.gitlab-ci.yml`,
проектные integration tests или другие навыки.

Адаптация:

- самостоятельные skills/ с UI metadata;
- единый профиль путей и соглашений, подключаемый OpenSpec;
- нейтральный общий контракт без внешней памяти и политики поставки источника;
- язык wiki/ответов и decision conventions целевого проекта;
- установщик с dry-run/preflight и нейтральный начальный корпус;
- дополнительные регрессионные проверки переносимости.

## Глоссарий и синонимы — 2026-10-05

Идея предпочтительного названия и явного списка нежелательных вариантов
заимствована из [domain-modeling / GLOSSARY-FORMAT.md](https://github.com/mattpocock/skills/blob/main/skills/engineering/domain-modeling/GLOSSARY-FORMAT.md)
набора Matt Pocock; [grill-with-docs](https://github.com/mattpocock/skills/blob/main/skills/engineering/grill-with-docs/SKILL.md)
подключает этот навык вместе с интервью. Это заимствование подхода, без
переноса кода или процедуры интервью.

Собственная адаптация: отдельные допустимые синонимы и названия «Избегать»
с причиной, контекстная эквивалентность по evidence, относительная ссылка
на основания, сохранение raw/идентификаторов и границ определения/применения.
Общие критерии перенесены из wiki-lint в wiki-query/references/glossary.md;
процедура проверки осталась в wiki-lint.
