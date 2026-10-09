# Детерминированная проверка корневых raw README.md

> Выполняется в текущей сессии в отдельном worktree по issue #20,
> с зависимостью #18. Для выполнения не нужны дополнительные внешние сервисы.

**Goal:** Проверять форму OKF v0.2 и локальный контракт новых raw-единиц,
сохраняя исходные материалы и согласованные процедуры навыков.

**Architecture:** Отдельный YAML-парсер/валидатор `_okf.py` и CLI `_raw.py`.
Команда `raw-lint` использует общий wiki-профиль. Парсер — PyYAML 6.0.3,
устанавливаемый явно; прочие команды сохраняют зависимости стандартной библиотеки.

**Tech Stack:** Python 3.10+, PyYAML 6.0.3, unittest, Markdown/YAML/JSON.

## Контракт

- Проверяются корневые README.md под raw/category/topic/unit, а не все вложенные
  Markdown-оригиналы. Область и проверенные файлы включаются в отчёт.
- По умолчанию сканируются категории из профиля. `[]` отключает автоматический
  выбор; явные пути позволяют проверить выбранные единицы внутри raw_root.
- Дефолтный режим raw проверяет дерево category/topic/YYYY-MM-DD-slug,
  наличие README.md, непустой Markdown body, type/title/description/sources,
  стабильные ID оснований, структуры метаданных, даты с UTC offset и локальные адреса.
- `--okf-only` проверяет форму концепта: настоящий YAML frontmatter и непустой
  строковый type. Optional metadata проверяются как producer guidance с warnings.
  Локальные дополнительные ограничения raw в этом режиме не применяются.
- Неизвестные поля допустимы. В режиме OKF неизвестные type допустимы;
  дефолтные типы Source material/Research study относятся к локальному raw-контракту.
- `verified` может быть списком или одиночным mapping. Отсутствие verified,
  generated, status и stale_after допустимо. Событие проверки не создаётся.
- Схемы проекта, заменяющие локальный raw-контракт, используют `--okf-only`
  и собственные проверки. Смысл schema CLI не интерпретирует.
- Без записи и сетевых запросов; источники и скрипты из metadata не выполняются.
  Диагностика не использует текущее время и не подтверждает истинность или свежесть.
- Symlinks за пределы checkout и ошибки чтения дают диагностику. Вложенные
  symlink-каталоги не обходятся рекурсивно. Старые категории не мигрируют.
- Коды: 0 — нет errors; 1 — найденные нарушения; 2 — ошибка вызова/профиля/зависимости.
  JSON и порядок findings стабильны; warnings не меняют код 0.
- Полное соответствие bundle, index/log, Markdown payloads, вычисления,
  runtime и аттестация не входят в проверку корневых файлов.

## Последовательность реализации

1. Добавить `tests/wiki_harness/test_raw.py`: CLI fixtures для валидных файлов,
   YAML block/flow/duplicates/unsafe tags, defaults/overrides/custom roots,
   отсутствующего root README, metadata, timestamp, source ID, containment,
   ошибок зависимости и неизменности всех байтов при первом запуске.
   Запустить выбранные тесты до реализации и подтвердить отсутствие команды.
2. Добавить `bin/wiki/_okf.py`: безопасный YAML loader с отказом от повторных
   mapping keys; валидатор формы концепта, присутствующих optional metadata
   и локального raw envelope. Не исполнять Python YAML tags или ресурсы.
3. Добавить `bin/wiki/_raw.py` и executable `bin/wiki/raw-lint`: разрешение
   профиля, детерминированный выбор единиц, containment, отчёт и коды 0/1/2.
   Добавить pinned `bin/wiki/requirements.txt`; missing dependency — code 2
   с инструкцией установки, без автоматической установки из команды.
4. Дополнить общий inventory `_kit.py` и package installation tests:
   installed raw-lint работает, missing resources блокируют установку до записи,
   CLI переносится в другой checkout, локальный maintainer не устанавливается.
5. Согласовать wiki-ingest/research/update/merge/lint/audit и общий контракт;
   обновить raw/profile/metadata references, README, neutral corpus и changelog.
   Требовать запуск для изменённого raw scope, сохранять report-only режим.
6. Проверить `python3 -m unittest discover -s tests -t .` в окружении с pinned
   parser, whitespace новых/staged файлов и temporary installation с CLI.
   Выполнить смысловой проход сценариев: источник, наблюдение, проверка,
   исследование, обновление, merge и report-only audit.
7. Подготовить PR в dev с Refs #18 и Refs #20, milestone 0.1.0 и связью Development.
   Merge/релиз выполняются только в рамках отдельного поручения пользователя.
