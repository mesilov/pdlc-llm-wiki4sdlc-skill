# Changelog

## Unreleased

### Added

- Проверка и обновление полного установленного wiki-набора с GitHub:
  `bin/wiki/update --check`, интерактивное обновление и `--force` без вопроса,
  каналы `main`/`release`, отдельный `skill-version.json`, backup и восстановление
  при ошибке записи. Профиль и корпус сохраняются; старые установки получают
  manifest через `scripts/update.py`. Навыки предлагают доступное обновление
  после одной разрешённой проверки в начале сессии.
  ([#7](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/7)).
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
