# Wiki Kit Updater Implementation Plan

> Для исполнения: согласованный issue #7, отдельный worktree, TDD и review перед PR.

**Goal:** обнаруживать обновления GitHub и обновлять весь установленный комплект.
**Architecture:** общий учёт ресурсов в `_kit.py`, GitHub/CLI/транзакция в `_update.py`,
два тонких entrypoint. Профиль и корпус исключены из управляемых ресурсов.
**Tech Stack:** Python 3.10+, standard library, unittest, GitHub REST API.

## 1. Manifest и установка

Файлы: `bin/wiki/_kit.py`, `scripts/install.py`, `tests/package/test_install.py`.

- [x] Написать тест: install создаёт `skill-version.json`, только skills/CLI входят
  в files, dirty и gitless source не выдают себя за точный upstream commit.
- [x] Выполнить `python3 -m unittest tests.package.test_install -v`; новый тест падает.
- [x] Вынести сбор и проверку комплекта в `kit_files(kit)`, возвращающий
  `dict[relative_destination, (bytes, mode)]`. Установщик использует те же ресурсы.
- [x] Добавить `make_manifest(files, repository, channel, commit, version=None,
  source_dirty=False)`, `manifest_bytes`, `read_manifest(root)`, `source_identity(kit)`.
  Constants: `MANIFEST='skill-version.json'`, `REPOSITORY='mesilov/pdlc-llm-wiki4sdlc-skill'`.
  Manifest schema_version=1, files: SHA-256, channel main/release, commit SHA или null.
- [x] Manifest проверяется до записи; идентичная установка не меняет mtime.
  `check_destination(path, root, alias=False)` отклоняет traversal и symlinks.
- [x] Повторить install tests; проверить в отдельном временном проекте.

## 2. GitHub и check

Файлы: `bin/wiki/_update.py`, `bin/wiki/update`, `scripts/update.py`,
`tests/package/test_update.py`.

- [x] Написать проверки main SHA, stable release tag → SHA, неизвестной старой
  установки, отсутствия сети/release и неизменности проекта при `--check --json`.
- [x] Выполнить `python3 -m unittest tests.package.test_update -v`, увидеть отсутствие updater.
- [x] `main(argv=None)` принимает project, --check, --json, --force, --channel main|release.
  JSON допустим только с check; check+force конфликтуют. Entry points отключают pycache.
- [x] Разрешить GitHub `/commits/main` или `/releases/latest` + `/commits/<tag>`.
  Проверить SHA, timeout и ограничить размер ответа. Полученный SHA закрепляет archive URL.
- [x] Коды: 0 нет обновления/успех, 1 доступно и не установлено, 2 ошибка.
  Без TTY вывод предложения без чтения stdin и без записи. Check не требует knowledge.
- [x] Повторить новые тесты; snapshot проекта совпадает до/после check.

## 3. Обновление и восстановление

Файлы: `_update.py`, `test_update.py`.

- [x] Добавить failing tests: согласие/отказ, force без stdin и та же SHA,
  bootstrap, локальные конфликты/backup, удаление только прежних managed resources,
  сохранение пользовательского профиля, корпуса и чужих файлов.
- [x] Добавить failing tests: архив traversal/symlink/incomplete, destination symlink,
  ошибочная запись с rollback. Не исполнять installer из скачанного архива.
- [x] Загружать tarball по SHA. Извлекать вручную только regular skills/CLI files,
  проверять пути/размер/полноту через kit_files; не использовать extractall.
- [x] Строить весь план до записи. Без force локальные конфликты блокируют план.
  Создавать `.wiki-kit-backups/<unique>/` с заменяемыми/удаляемыми файлами и manifest.
  Записывать отдельные файлы атомарно, manifest последним. При ошибке восстановить
  прежние bytes/modes, удалить созданные файлы; backup оставить доступным.
- [x] Повторить test_update, затем весь unittest suite.

## 4. Инструкции, review и поставка

Файлы: `README.md`, `skills/wiki-query/references/contract.md`, `CHANGELOG.md`.

- [x] Добавить примеры check/update/force/channel и bootstrap, backup/return codes,
  ограничения старой установки и отличие от skills CLI.
- [x] В контракте: одна разрешённая сетевыми правилами проверка в начале сессии,
  предложение без самовольного update, отказ сети не блокирует wiki, без updater
  не устанавливать его в чужой проект автоматически.
- [x] Проверить сценарии решений с агентом и валидатор навыков.
- [x] Запустить `python3 -m unittest discover -s tests -t .`, `git diff --check`,
  whitespace для новых файлов, временную установку и installed CLI.
- [x] Пройти независимый code review, исправить actionable замечания, повторить
  затронутые проверки.
- [ ] Staged scope/check; commit, push и PR в dev, milestone 0.1.0.
  Связать issue #7, приложить PR к текущему чату. Не выполнять merge/release.
