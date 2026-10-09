# Changelog

## Unreleased

### Added

- `bin/wiki/doctor` проверяет Git remote целевого проекта и запуск `gh` или
  `glab`. Явные `--forge-network` и `--require-forge` проверяют авторизацию
  на нужном хосте и чтение репозитория, issue и PR/MR; `--forge-remote` и
  `--forge-provider` позволяют выбрать remote и корпоративный provider.
  Отчёт отделяет чтение и заявленные API права от непроверенной записи,
  не раскрывает сырой вывод клиентов. По умолчанию сеть выключена;
  forge остаётся необязательным для локальной wiki.
  [#12](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/12).

- Установщик спрашивает, для какого агента установить набор: Claude Code,
  Codex или OpenCode. Параметр `--agent` пропускает меню; без TTY сохраняется
  прежняя установка в `.agents/skills`, старый `--claude` остаётся совместимым.
  Dry-run показывает выбранного агента и пути до записи.
  ([#6](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/6)).
- Локальный навык `pdlc-wiki-maintainer`: изменения через issue и PR в `dev`,
  обязательная запись changelog внутри PR, снятие всех замечаний перед merge
  и выпуск из `dev` в защищённую `main` через GitHub milestone.
  ([#5](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/5)).

- Команда `bin/wiki/doctor` проверяет пути wiki-профиля и доступность OpenSpec
  CLI и skills для Codex, Claude Code и OpenCode. Она показывает найденные
  пути и подсказки в текстовом или JSON-отчёте, поддерживает строгую проверку
  и таймаут CLI, сохраняет правильный executable при относительном PATH,
  работает только на чтение и переносится установщиком.
  OpenSpec остаётся необязательным. Проверка файлов навыков не подтверждает
  их загрузку активным агентом или полноту workflow profile.
  [#4](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/4).

### Fixed

- Уточнена связь issue с PR в `dev` и ручное закрытие выполненного запроса
  после merge, чтобы milestone не блокировался из-за игнорируемого `Closes`.
  ([#5](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/5)).
