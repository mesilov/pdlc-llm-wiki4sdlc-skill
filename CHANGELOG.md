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
  ([#12](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/12)).

- Проверка и обновление полного установленного wiki-набора с GitHub:
  `bin/wiki/update --check`, интерактивное обновление и `--force` без вопроса,
  каналы `main`/`release`, отдельный `skill-version.json` с хешами и правами
  файлов, backup и восстановление при ошибке записи. Профиль и корпус
  сохраняются; старые установки получают
  manifest через `scripts/update.py`. Навыки предлагают доступное обновление
  после одной разрешённой проверки в начале сессии.
  ([#7](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/7)).

- Выбор агента при установке: меню для Claude Code, Codex и OpenCode или
  параметр `--agent claude|codex|opencode` для запуска без меню. Полный набор
  навыков устанавливается в `.agents/skills/`; для Claude Code добавляются
  относительные ссылки из `.claude/skills/`. `--dry-run` показывает агента и
  целевые пути до записи. Без TTY и без параметров выбора используется Codex
  с прежними путями установки; `--claude` совместим с `--agent claude`.
  ([#6](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/6),
  [#16](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/16)).

- Команда `bin/wiki/doctor` проверяет пути wiki-профиля и доступность OpenSpec
  CLI и skills для Codex, Claude Code и OpenCode. Она показывает найденные
  пути и подсказки в текстовом или JSON-отчёте, поддерживает строгую проверку
  и таймаут CLI, сохраняет правильный executable при относительном `PATH`,
  работает только на чтение и переносится установщиком.
  OpenSpec остаётся необязательным. Проверка файлов навыков не подтверждает
  их загрузку активным агентом или полноту workflow profile.
  ([#4](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/4)).

- Локальный навык `pdlc-wiki-maintainer`: изменения через issue и PR в `dev`,
  обязательная запись changelog внутри PR, снятие всех замечаний перед merge
  и продвижение `dev → main` через релизный PR и GitHub milestone.
  ([#5](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/5)).

### Fixed

- Уточнены ручная связь issue с PR в `dev` и закрытие выполненного запроса
  после merge в `dev`: `Closes #N` для PR вне default branch не закрывает
  issue, поэтому завершение задачи milestone проверяется явно.
  ([#5](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/5)).
