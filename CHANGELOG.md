# Changelog

## Unreleased

### Added

- Команда `bin/wiki/doctor` проверяет пути wiki-профиля и доступность OpenSpec
  CLI и skills для Codex, Claude Code и OpenCode. Она показывает найденные
  пути и подсказки в текстовом или JSON-отчёте, поддерживает строгую проверку
  и таймаут CLI, работает только на чтение и переносится установщиком.
  OpenSpec остаётся необязательным. Проверка файлов навыков не подтверждает
  их загрузку активным агентом или полноту workflow profile.
  [#4](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/4).
