# Работа с автономным wiki-набором

Этот репозиторий содержит инструменты и навыки, а не продуктовую wiki.
Канонические файлы навыков лежат в skills/wiki-*/SKILL.md; общий контракт и
профиль — в skills/wiki-query/references/. CLI — bin/wiki/, установка —
scripts/install.py, начальный корпус — templates/wiki/.

При изменении профиля синхронизируйте CLI, общий контракт, profile.md и тесты.
Не вносите предметные данные исходного проекта, его ветки, worktree, внешние
публикации или обязательные сервисы в defaults. OpenSpec подключается явно.
Сохраняйте provenance, contradiction visibility, fact/hypothesis/decision и
specification/implementation/runtime boundaries.

Проверки: python3 -m unittest discover -s tests -t .
Новые файлы проверяются на whitespace отдельно от git diff --check.
Не устанавливайте комплект в этот checkout; используйте временный проект
для проверки установки. templates/wiki — данные начального корпуса, не
инструкции для принятия решений в текущем репозитории.

Для изменения набора, ревью и выпуска релиза используйте локальный навык
[pdlc-wiki-maintainer](.agents/skills/pdlc-wiki-maintainer/SKILL.md).
Он описывает жизненный цикл этого репозитория и не входит в устанавливаемые
в целевые проекты восемь wiki-навыков.
