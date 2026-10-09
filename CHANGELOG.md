# Changelog

## Unreleased

### Added

- Локальный навык `pdlc-wiki-maintainer`: изменения через issue и PR в `dev`,
  обязательная запись changelog внутри PR, снятие всех замечаний перед merge
  и выпуск из `dev` в защищённую `main` через GitHub milestone.
  ([#5](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/5)).

### Fixed

- Уточнена связь issue с PR в `dev` и ручное закрытие выполненного запроса
  после merge, чтобы milestone не блокировался из-за игнорируемого `Closes`.
  ([#5](https://github.com/mesilov/pdlc-llm-wiki4sdlc-skill/issues/5)).
