# Самодиагностика gh/glab — issue #12

Основание: пользователь одобрил scope [issue #12](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/12) и поручил реализацию. Базовый doctor уже merged в dev. Новый PR направляется в dev, milestone 0.1.0; Merge в dev выполняется по отдельному поручению пользователя; релиз остаётся отдельным этапом.

## Интерфейс и границы

Doctor по умолчанию проверяет Git remote целевого checkout и соответствующий gh/glab через --version без сети. Отсутствующая интеграция даёт warning/skipped. --forge-network явно разрешает сетевые проверки; --require-forge включает их и требует подтверждённые авторизацию и чтение репозитория, issue и PR/MR. --forge-remote NAME выбирает remote, когда их несколько; --forge-provider github|gitlab явно задаёт provider корпоративного хоста. github.com и gitlab.com распознаются автоматически. Неизвестный хост не считается GitLab. Новые поля wiki.config.json не нужны.

Выбор remote не использует окружение GH_REPO/GLAB_REPO и upstream wiki-набора. HTTPS и SSH URLs приводятся к безопасному host/path; credential-bearing URLs, query и fragment отклоняются без публикации исходного URL. Нестандартный HTTPS API port сохраняется для GitLab, а для GitHub явно отклоняется как unsupported_port: реальный gh не принимает host:port в --hostname. Port 443 нормализуется; SSH port не переносится в API. GitHub имя проверяется без учёта регистра; local/worktree remotes учитываются, global/system remotes не выбирают цель. Несколько fetch URLs одного remote также неоднозначны. Git subprocess проверяет собственный checkout при --project, включая worktree, и не подменяет проект родительским репозиторием.

## Проверки и архитектура

Новый bin/wiki/_forge.py отвечает за remote, клиент и API; _doctor.py подключает его результаты к checks и общему отчёту. Запуски выполняются argv без shell, stdin=DEVNULL, абсолютным executable, с --timeout на каждый вызов и отключением prompts/debug/pager. Не копируются stderr, stdout API, exception text и произвольные поля API в отчёт. Разрешены только валидированные identity, версия и права, чтобы не раскрыть секреты.

Сетевые запросы выполняются через выбранный CLI с явным --hostname и --method GET. Первый запрос user подтверждает авторизацию на нужном хосте. Далее проверяются repository/project с совпадением полного имени и web host, issue и pulls/merge_requests (по одной записи, без pagination). Пустой список является успешным чтением; отключённая функция не считается готовой. Ошибки клиента, 401/403/404, сеть, timeout, invalid JSON/schema и несовпадение identity дают раздельные checks и подсказки. Проверка чтения API не доказывает запись. GitHub permissions и GitLab access_level отражаются только как сведения API; forge.write всегда сообщает, что запись не проверялась.

Документация сохраняет различие локального executable, авторизации, API чтения, заявленных прав и выполненной записи. Диагностика не меняет проект, клиент или forge и не требует внешнего сервиса для локальной wiki.

## Варианты

1. Проверять только --version: недостаточно для принятого scope.
2. Делать API запросы при каждом doctor: создаёт обязательную сетевую зависимость.
3. Локальная проверка по умолчанию, API opt-in, отдельный strict: выбранный вариант, сохраняет автономность набора.

## Приёмка

Тесты через подставные CLI проверяют оба provider, target selection, корпоративные хосты, malformed URLs/API, отсутствующие клиенты/auth/access, отключённые функции, timeout, секреты, пустые списки и read-only. Полный unittest suite и whitespace checks обязательны. Установку проверяем только в отдельном временном проекте; установщик обязан переносить _forge.py. Реальный GitHub read-only запуск дополнительно подтверждает совместимость текущего gh; mock проверки не являются runtime доказательством GitLab.

## Первичные источники API (проверены 2026-10-09)

- [gh api](https://cli.github.com/manual/gh_api): явные hostname/method, REST path.
- [glab api](https://docs.gitlab.com/cli/api/): hostname и GET.
- [GitHub repositories API](https://docs.github.com/en/rest/repos/repos#get-a-repository): identity и permissions.
- [GitLab projects API](https://docs.gitlab.com/api/projects/): project identity и permissions.
