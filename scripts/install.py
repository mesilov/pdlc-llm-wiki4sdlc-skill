#!/usr/bin/env python3
"""Install the complete wiki kit into an existing project; never overwrite edits."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(KIT / 'bin/wiki'))
# Validate the helper before importing it; the ordinary inventory validates
# every remaining resource once this bootstrap dependency is available.
helper = KIT / 'bin/wiki/_kit.py'
for component in (KIT / 'bin', KIT / 'bin/wiki', helper):
    if component.is_symlink():
        print(f'Ошибка установки: запись через symlink запрещена: {component}', file=sys.stderr)
        raise SystemExit(2)
if not helper.is_file():
    print('Ошибка установки: Неполный комплект: bin/wiki/_kit.py', file=sys.stderr)
    raise SystemExit(2)
from _kit import (MANIFEST, REPOSITORY, SKILLS, check_destination, kit_files,
                  make_manifest, manifest_bytes, read_manifest, source_files, source_identity)

AGENTS = {'claude': 'Claude Code', 'codex': 'Codex', 'opencode': 'OpenCode'}


def select_agent(agent: str | None, claude: bool):
    if claude:
        if agent not in (None, 'claude'):
            raise ValueError('--claude несовместим с --agent ' + agent)
        return 'claude'
    if agent:
        return agent
    if not sys.stdin.isatty():
        return 'codex'
    print('Для какого агента установить навыки?')
    choices = {}
    for number, (name, label) in enumerate(AGENTS.items(), 1):
        print(f'  {number}. {label}')
        choices[str(number)] = name
        choices[name] = name
    while True:
        try:
            answer = input('Выбор [1-3 или имя; q — отмена]: ').strip().lower()
        except EOFError:
            raise ValueError('Ввод завершён до выбора агента; используйте --agent') from None
        if answer == 'q':
            return None
        if answer in choices:
            return choices[answer]
        print('Некорректный выбор. Введите 1, 2, 3, claude, codex или opencode.')


def installation_plan(root: Path, init_wiki: bool, claude: bool, managed):
    if init_wiki:
        required = [Path('templates/wiki') / name for name in (
            'wiki.config.json', 'raw/README.md', 'knowledge/SCHEMA.md',
            'knowledge/index.md', 'knowledge/GLOSSARY.md', 'knowledge/synthesis.md',
            'knowledge/ASSUMPTIONS.md', 'knowledge/OPEN-QUESTIONS.md', 'knowledge/log.md')]
        for relative in required:
            check_destination(KIT / relative, KIT)
            if not (KIT / relative).is_file():
                raise ValueError(f'Неполный комплект: {relative}')
    files = []
    for relative in managed:
        if relative.startswith('.agents/skills/'):
            source = KIT / 'skills' / Path(relative).relative_to('.agents/skills')
        else:
            source = KIT / relative
        files.append((source, root / relative))
    if init_wiki:
        folder = KIT / 'templates/wiki'
        files.extend((source, root / source.relative_to(folder)) for source in source_files(folder, KIT))
    copies = []
    for source, target in files:
        check_destination(target, root)
        if target.exists():
            if not target.is_file() or target.read_bytes() != source.read_bytes():
                raise ValueError(f'Конфликт: существующий файл не будет перезаписан: {target}')
        else:
            copies.append((source, target))
    links = []
    if claude:
        for name in SKILLS:
            alias = root / '.claude/skills' / name
            canonical = root / '.agents/skills' / name
            check_destination(alias, root, alias=True)
            if alias.is_symlink() and alias.resolve() == canonical.resolve():
                continue
            if alias.exists() or alias.is_symlink():
                raise ValueError(f'Конфликт: существующий путь не будет заменён: {alias}')
            links.append((alias, canonical))
    return copies, links


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path, help='existing destination project directory')
    parser.add_argument('--init-wiki', action='store_true', help='also copy a neutral corpus and profile')
    parser.add_argument('--agent', choices=AGENTS,
                        help='target agent; otherwise prompt in a terminal, or use codex without a TTY')
    parser.add_argument('--claude', action='store_true', help='compatibility alias for --agent claude')
    parser.add_argument('--channel', choices=('main', 'release'), help='update channel; retain installed channel by default')
    parser.add_argument('--dry-run', action='store_true', help='check conflicts and show planned writes')
    args = parser.parse_args()
    root = args.project.resolve()
    try:
        if not root.is_dir():
            raise ValueError(f'Каталог проекта не существует: {root}')
        if root == KIT or KIT.is_relative_to(root):
            raise ValueError('Устанавливайте комплект в отдельный целевой проект')
        agent = select_agent(args.agent, args.claude)
        if agent is None:
            print('Установка отменена. Файлы не изменены.')
            return 0
        existing = read_manifest(root)
        if existing and existing['repository'] != REPOSITORY:
            raise ValueError('Конфликт: skill-version.json относится к другому repository')
        managed = kit_files(KIT)
        if existing and set(existing['files']) - set(managed):
            raise ValueError('Конфликт: для удаления старых ресурсов используйте bin/wiki/update')
        channel = args.channel or (existing['channel'] if existing else 'main')
        manifest = make_manifest(managed, REPOSITORY, channel, **source_identity(KIT))
        content = manifest_bytes(manifest)
        manifest_path = root / MANIFEST
        write_manifest = not manifest_path.exists() or manifest_path.read_bytes() != content
        copies, links = installation_plan(root, args.init_wiki, agent == 'claude', managed)
        print(f'Агент: {AGENTS[agent]}')
        print(f'Проект: {root}')
        print('Навыки: .agents/skills/; CLI: bin/wiki/')
        if agent == 'claude':
            print('Обнаружение Claude Code: .claude/skills/ -> .agents/skills/')
        for source, target in copies:
            print(f'{"План" if args.dry_run else "Копирование"}: {target.relative_to(root)}')
            if not args.dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        for alias, canonical in links:
            relative = os.path.relpath(canonical, alias.parent)
            print(f'{"План" if args.dry_run else "Ссылка"}: {alias.relative_to(root)} -> {relative}')
            if not args.dry_run:
                alias.parent.mkdir(parents=True, exist_ok=True)
                alias.symlink_to(relative, target_is_directory=True)
        if write_manifest:
            print(f'{"План" if args.dry_run else "Запись"}: {MANIFEST}')
            if not args.dry_run:
                manifest_path.write_bytes(content)
        print(f'Файлов: {len(copies)}; ссылок: {len(links)}. AGENTS.md задаётся проектом.')
        return 0
    except (ValueError, OSError) as error:
        print(f'Ошибка установки: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
