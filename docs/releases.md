# CI и выпуск релизов

Дата настройки: 2026-10-06.

## Подход и источник

За основу взят [mattpocock/skills](https://github.com/mattpocock/skills),
проверенный на commit `4588b32ecab9ecc9fc8cc6b6c5e7d675b6004b0d`:
[release.yml](https://github.com/mattpocock/skills/blob/4588b32ecab9ecc9fc8cc6b6c5e7d675b6004b0d/.github/workflows/release.yml),
[package.json](https://github.com/mattpocock/skills/blob/4588b32ecab9ecc9fc8cc6b6c5e7d675b6004b0d/package.json),
[Changesets config](https://github.com/mattpocock/skills/blob/4588b32ecab9ecc9fc8cc6b6c5e7d675b6004b0d/.changeset/config.json).

Перенесены Changesets, единая версия комплекта, release PR, запуск после push
в main, последовательные выпуски и tagging приватного пакета. Для нашего
Python-набора добавлены проверки перед выпуском. Changelog формируется локальным
стандартным formatter Changesets; синхронизация Claude plugin не требуется.
Все Actions закреплены по commit SHA. Changesets Action v1.5.3 совместим с CLI v2;
ветка main у upstream Action уже использует другой контракт v2/CLI v3.

## Как проходит выпуск

1. В PR с изменением комплекта добавьте описание через `npm run changeset`.
   `patch` — совместимое исправление, `minor` — новая совместимая возможность,
   `major` — несовместимое изменение. До 1.0 Changesets следует SemVer для
   версии 0.x; проверьте итоговую версию в release PR.
2. CI проверяет весь комплект на Ubuntu с Python 3.10 и 3.13, а также macOS с
   Python 3.13. Установка, aliases и CLI проверяются в временных проектах
   существующими тестами. Отдельно валидируются описания Changesets и lockfile.
3. После merge в main workflow Release повторяет CI и создаёт либо обновляет
   `changeset-release/main`: бот меняет package.json, package-lock.json,
   CHANGELOG.md и удаляет использованные changesets. Перед записью release PR
   команда version синхронизирует lockfile и запускает тесты на результате
   изменения версии.
4. Проверьте release PR и выполните merge, когда готовы выпускать версию.
   Следующий Release запускает проверки, затем `changeset tag`. Action пушит
   `vX.Y.Z` и создаёт GitHub Release с записью из CHANGELOG.md. В GitHub Release
   доступны автоматические source archives со всем комплектом.

Новые changesets до merge release PR обновляют его. Пустой changeset не нужен
для каждого служебного изменения. npm-публикации нет: `private: true`, а команда
publish workflow выполняет только tagging. Node.js 22 и npm нужны разработчикам
для релиза; установка и CLI набора по-прежнему требуют только Python 3.10+.
Первый changeset поднимает техническую версию 0.0.0 до 0.1.0.

## GitHub settings и повторный запуск

Actions должны быть включены. В Settings → Actions → General включите
`Allow GitHub Actions to create and approve pull requests`: этот общий переключатель
нужен для создания release PR. Сам workflow не одобряет и не сливает PR.
Default workflow permissions могут оставаться `read`; права `contents: write`
и `pull-requests: write` выданы только release job. Достаточно встроенного
GITHUB_TOKEN, отдельный PAT или npm token не нужен.

PR и теги, созданные GITHUB_TOKEN, не запускают новые workflow автоматически
([GitHub docs](https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-when-your-workflow-runs/triggering-a-workflow)).
Поэтому выпуск не зависит от отдельного workflow на tag, а проверки результата
version выполняются внутри Release. Для ручной проверки bot PR запустите CI
с ветки `changeset-release/main` через Actions → Run workflow.

Release можно повторно запустить через Actions → Release → Run workflow на main.
На других ветках release jobs пропускаются. Если тег уже существует, Changesets
не создаёт его повторно. Если предыдущий запуск успел запушить тег, но упал при
создании GitHub Release, проверьте SHA тега и вручную создайте отсутствующий
Release с нужной секцией CHANGELOG.md; обычный повторный tagging его не восстановит.

## Локальная проверка без выпуска

На 2026-10-06 `npm audit` для CLI 2.31.1 сообщает один upstream advisory
[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm):
DoS при разборе глубоко вложенных glob patterns в `braces` (15 записей вместе
с зависимыми пакетами). Последняя доступная версия braces 3.0.3 тоже затронута.
Это dev dependency релизного инструмента; в устанавливаемый Python-комплект
она не копируется. Не передавайте релизному инструменту недоверенные glob patterns;
при обновлении tooling повторяйте audit.

```bash
python3 -m unittest discover -s tests -t .
npm ci
npm run changeset -- status
```

`npm run version` изменяет версию и changelog; запускайте его для проверки только
в временной копии. `npm run tag` создаёт локальный тег, поэтому для smoke-test
также нужен отдельный временный Git-репозиторий. Не устанавливайте набор в его
checkout. При установке из релиза распакуйте source archive и выполните
`python3 scripts/install.py /path/to/project --init-wiki --dry-run`, затем установку.
