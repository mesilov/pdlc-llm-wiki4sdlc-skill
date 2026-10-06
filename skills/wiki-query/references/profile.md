# Профиль целевого проекта

`wiki.config.json` — JSON object в корне целевого проекта. CLI и все восемь
skills используют один профиль. Неизвестное поле, неверный тип или небезопасный
путь — ошибка без fallback. JSON хранит данные и не задаёт команды.
Метаданные помогают агенту выбрать контекст, но не разрешают внешние действия.

## Поля

| Поле | Дефолт / назначение |
| --- | --- |
| project_name | Не задан; имя из инструкций проекта |
| context | Не задан; краткий предметный контекст, без собственных правил агента |
| language | Не задан; язык wiki и ответа из запроса/проекта |
| corpus_root | `.`; общий родитель дефолтных raw/knowledge |
| raw_root | `<corpus_root>/raw`; явное значение относительно project root |
| knowledge_root | `<corpus_root>/knowledge`; явное значение относительно project root |
| openspec_root | `null`; выключено. Строка подключает существующий каталог |
| documents | Имена supporting документов относительно knowledge_root, см. ниже |
| layers | Имена слоёв относительно knowledge_root, см. ниже |
| scan_files | `['README.md', 'AGENTS.md']`; дополнительные проверяемые Markdown файлы относительно project root |
| decision_name_pattern | `^\d{4}-(?:0[1-9]\|1[0-2])-[a-z0-9]+(?:-[a-z0-9]+)*\.md$`; Python regex, fullmatch имени файла |
| decision_statuses | Не заданы; proposed/accepted/rejected/superseded по умолчанию, значения нестандартных статусов описывает schema |
| glossary_sort | `latin-cyrillic`; альтернативный `unicode` для порядка по нормализованным Unicode code points |
| views | `['product', 'discovery', 'experience', 'engineering', 'go-to-market', 'operations', 'measurement']`; явный список заменяет defaults |
| raw_categories | Не заданы; категории evidence из schema, новые выбираются по смыслу источника |

project_name/context/language — непустые строки. decision_statuses/views/
raw_categories — списки непустых строк. Эти поля используются агентом;
CLI не проверяет смысл claims, язык prose, принятие решения или соответствие
статуса полномочиям. Диагностика CLI сейчас выводится на русском независимо
от языка wiki. Исходные источники и технические идентификаторы не переводятся.

[Семь тематических линз](pdlc.md) охватывают вопросы PDLC и SDLC.
`views` задаёт ключи линз; `layers.views` задаёт каталог представлений.
По умолчанию путь линзы — `knowledge/views/<lens>/`.
С учётом профиля путь имеет вид `<knowledge_root>/<layers.views>/<lens>/`.
Линзы не задают статусы и обязательную последовательность работ.

Явный список `views`, включая `[]`, заменяет defaults без дополнения.
Опишите цели и расположение своих линз в schema/index.
При отсутствии поля специальная карта schema/index имеет приоритет для агента.
CLI использует список профиля или defaults, но не читает смысл этой карты.
`status` считает страницы под `layers.views` и в прежних каталогах представлений внутри `knowledge_root`.
Команда не оценивает достижение целей.
Старая карта и папки существующей wiki сохраняются до явного запроса на изменение структуры.

`documents` принимает только ключи:

| Ключ | Дефолт |
| --- | --- |
| schema | SCHEMA.md |
| index | index.md |
| synthesis | synthesis.md |
| assumptions | ASSUMPTIONS.md |
| open_questions | OPEN-QUESTIONS.md |
| glossary | GLOSSARY.md |
| log | log.md |

Все documents, кроме schema/index, можно отключить явным `null`. Это
пропускает операции над отдельным supporting документом, но не отменяет
необходимость сохранить assumptions, unknowns и provenance в действующих
страницах. Включённый glossary обязан содержать непустые H2-определения.
Schema/index нужны навыкам; CLI сообщает отсутствие index как warning.
Структуру и порядок glossary проверяет CLI; определения и варианты названий —
semantic review по [общим правилам глоссария](glossary.md). Смысл остальных
supporting документов также проверяется при semantic review.

`layers` принимает только ключи:

| Ключ | Дефолт |
| --- | --- |
| domains | domains |
| views | views |
| decisions | decisions |
| inbox | inbox |
| archive | archive |

Каталоги создаются при появлении содержимого. Все строки путей
непустые, относительные, без `..` и абсолютных путей; symlinks не могут
выводить их за границу соответствующего корня. Raw/knowledge/OpenSpec не
вложены друг в друга, каталоги layers не пересекаются. --fix отказывается
писать glossary через symlink, даже внутренний. Скрипт не переименовывает
файлы, не мигрирует корпус и не генерирует semantic index.

`latin-cyrillic`: латиница, кириллица, остальные символы; casefold, NFC,
backticks и пробелы нормализуются, ё идёт вместе с е. `unicode`: NFC/casefold
сравниваются по code points; это детерминированная сортировка, не языковой
словарь. Исходные определения и code blocks при сортировке сохраняются.

## Пример существующей wiki без OpenSpec

```json
{
  "project_name": "Laboratory",
  "context": "Методики и результаты экспериментов",
  "language": "en",
  "raw_root": "docs/evidence",
  "knowledge_root": "docs/wiki",
  "openspec_root": null,
  "documents": {
    "index": "navigation.md",
    "glossary": "terms.md",
    "synthesis": null
  },
  "layers": {"domains": "topics", "views": "lenses", "decisions": "adr"},
  "decision_name_pattern": "^ADR-[0-9]+[.]md$",
  "decision_statuses": ["draft", "approved", "replaced"],
  "glossary_sort": "unicode",
  "views": ["research", "operations"],
  "raw_categories": ["interviews", "experiments", "sources"],
  "scan_files": ["README.md", "AGENTS.md"]
}
```

В schema этого проекта должны быть описаны draft/approved/replaced и права
принятия. Пример не создаёт новые defaults для других проектов.

## Трассировка wiki ↔ OpenSpec

При явном `openspec_root` [карта трассировки](traceability.md) связывает требования и сценарии wiki с OpenSpec.
Карты `traceability.json` лежат под `layers.domains` внутри `knowledge_root`.
`wiki_files` задаёт область wiki; `specs` содержит явные пары `{capability, path}` относительно OpenSpec root.
`decisions` указывает основания выбора из слоя решений.
Стабильные `[ID]` связывают Requirement и Scenario без зависимости от их названий.

`bin/wiki/trace [feature] --json` проверяет структуру только заявленных областей.
`--require-reviewed` также требует ручной статус `reviewed` и совпадение review fingerprint.
CLI не объединяет delta и main specs, не проверяет смысл и не подтверждает runtime.
После archive вручную выберите актуальные specs.
Повторите проверку карты.

## Что остаётся в AGENTS.md проекта

Профиль задаёт данные и пути. Команды tests/validation, обязательность
спецификации для изменения поведения, worktree, remote, branch, commit,
PR/MR, CI, merge и публикацию задаёт целевой харнес. Их отсутствие не
разрешает агенту подставить правила исходного проекта. Перед выполнением
дополнительной проверки проверьте, что команда существует и относится к scope.

Если проект использует OpenSpec, явно добавьте `"openspec_root": "openspec"`
или свой путь. При отсутствии каталога все CLI команды завершатся кодом 2
до исправлений. Недоступность openspec CLI ограничивает проверку изменённых
specs, но не мешает чтению знаний; автоматическая установка не выполняется.
