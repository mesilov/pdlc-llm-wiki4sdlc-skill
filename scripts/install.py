#!/usr/bin/env python3
"""Install the complete wiki kit into an existing project; never overwrite edits."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
SKILLS = ('wiki-audit', 'wiki-decide', 'wiki-ingest', 'wiki-lint',
          'wiki-merge', 'wiki-query', 'wiki-research', 'wiki-update')


def source_files(directory: Path):
    return sorted(p for p in directory.rglob('*') if p.is_file() and
                  '__pycache__' not in p.parts and p.suffix != '.pyc')


def check_destination(path: Path, root: Path, *, alias=False):
    current = path.parent if alias else path
    while current != root:
        if current.is_symlink():
            raise ValueError(f'Конфликт: запись через symlink запрещена: {current}')
        if current != path and current.exists() and not current.is_dir():
            raise ValueError(f'Конфликт: родитель не является каталогом: {current}')
        current = current.parent


def installation_plan(root: Path, init_wiki: bool, claude: bool):
    required = [Path('skills') / name / 'SKILL.md' for name in SKILLS]
    required.extend(Path('skills/wiki-query/references') / name
                    for name in ('contract.md', 'profile.md', 'glossary.md', 'pdlc.md', 'writing.md', 'traceability.md', 'metadata.md'))
    required.extend(Path('skills/wiki-query/references/utr-source') / name for name in (
        'skills/simple-russian/SKILL.source.md',
        'skills/simple-russian/references/checklist.md',
        'skills/simple-russian/references/use-cases.md',
        'examples/before-after-ru.md', 'examples/before-after.md',
        'evals/utr_lint.py', 'evals/md_blocks.py', 'LICENSE', 'manifest.json'))
    required.extend(Path('bin/wiki') / name
                    for name in ('_core.py', '_trace.py', '_doctor.py', 'lint', 'status', 'find-orphans', 'affected', 'trace', 'doctor'))
    if init_wiki:
        required.extend(Path('templates/wiki') / name for name in (
            'wiki.config.json', 'raw/README.md', 'knowledge/SCHEMA.md',
            'knowledge/index.md', 'knowledge/GLOSSARY.md', 'knowledge/synthesis.md',
            'knowledge/ASSUMPTIONS.md', 'knowledge/OPEN-QUESTIONS.md', 'knowledge/log.md'))
    for relative in required:
        if not (KIT / relative).is_file():
            raise ValueError(f'Неполный комплект: {relative}')
    files = []
    for name in SKILLS:
        folder = KIT / 'skills' / name
        files.extend((source, root / '.agents/skills' / name / source.relative_to(folder))
                     for source in source_files(folder))
    files.extend((source, root / 'bin/wiki' / source.relative_to(KIT / 'bin/wiki'))
                 for source in source_files(KIT / 'bin/wiki'))
    if init_wiki:
        folder = KIT / 'templates/wiki'
        files.extend((source, root / source.relative_to(folder)) for source in source_files(folder))
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
    parser.add_argument('--claude', action='store_true', help='add relative .claude/skills aliases')
    parser.add_argument('--dry-run', action='store_true', help='check conflicts and show planned writes')
    args = parser.parse_args()
    root = args.project.resolve()
    try:
        if not root.is_dir():
            raise ValueError(f'Каталог проекта не существует: {root}')
        if root == KIT or KIT.is_relative_to(root):
            raise ValueError('Устанавливайте комплект в отдельный целевой проект')
        copies, links = installation_plan(root, args.init_wiki, args.claude)
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
        print(f'Файлов: {len(copies)}; ссылок: {len(links)}. AGENTS.md задаётся проектом.')
        return 0
    except (ValueError, OSError) as error:
        print(f'Ошибка установки: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
