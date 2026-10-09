# Forge doctor Implementation Plan

> For agentic workers: use superpowers:subagent-driven-development for implementation and independent spec/quality review.

**Goal:** выполнить scope issue #12 в PR на dev.
**Architecture:** отдельный _forge.py возвращает checks через существующий add; _doctor.py задаёт flags и показывает результаты. Новые поля профиля не добавляются.
**Tech Stack:** Python 3.10+, stdlib subprocess/json/unittest, Git, gh/glab.

## Task 1: Клиенты, API и интеграция установки

Файлы: bin/wiki/_forge.py (новый), bin/wiki/_doctor.py, bin/wiki/_kit.py (inventory установки/обновления), tests/wiki_harness/test_forge_doctor.py (новый), tests/package/test_install.py.

- [ ] Написать failing CLI tests: стандартный doctor без сетевых команд; явный --forge-network с GitHub/GitLab fixtures; --require-forge не скрывает отсутствие доступа. Команда: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.wiki_harness.test_forge_doctor -v. До реализации ожидается failure из-за отсутствия flags/checks.
- [ ] Реализовать локальный target selection/remote parser, безопасный bounded subprocess и явный provider. Протокол: check_forge(root, checks, add, *, remote, provider, network, required, timeout) добавляет forge.target, forge.cli, forge.auth, forge.repository, forge.issues, forge.pull_requests, forge.permissions, forge.write.
- [ ] Реализовать GET user, repository/project, issues и pulls/merge_requests через --hostname. Валидировать JSON type и identity; не печатать произвольные API поля и stderr. Проверить отключённые функции и partial failures.
- [ ] Добавить fixtures для неверного хоста, нескольких remotes/URLs, Git worktree, --project/nested cwd, relative PATH, auth только на другом host, сети, timeout, неверных ответов и credential-bearing URL. Проверять argv и отсутствие записывающих вызовов.
- [ ] Переносить _forge.py установщиком и проверять missing payload preflight. Запустить targeted tests до зелёного результата.

## Task 2: Контракт, документация, changelog

Файлы: README.md, skills/wiki-query/references/contract.md, profile.md, CHANGELOG.md.

- [ ] Описать flags, выбор target, local/online/strict поведение, JSON checks и непроверенную запись.
- [ ] Добавить в Unreleased содержательное описание изменения со ссылкой #12.
- [ ] Проверить примеры и относительные Markdown ссылки; sync новых defaults не нужен, поскольку новых полей профиля нет.

## Task 3: Верификация, review, доставка

- [ ] Полный PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t .
- [ ] Установка dry-run и фактическая через --agent codex --init-wiki в TemporaryDirectory; запуск installed doctor и snapshot bytes/mtime до/после.
- [ ] Независимое review сначала соответствия issue, затем качества кода; исправить найденные проблемы и повторить соответствующие проверки.
- [ ] git diff --check; untracked whitespace/newline; git diff --cached --check; проверить staged scope.
- [ ] Fetch актуального dev, проверить diff, commit, push codex/wiki-forge-doctor, PR строго на dev, milestone 0.1.0, Refs #12 и Development link. Проверить сохранённый head и checks; merge не выполнять.
