"""Shared managed-file inventory and installed wiki-kit provenance."""
from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath

SKILLS = ('wiki-audit', 'wiki-decide', 'wiki-ingest', 'wiki-lint',
          'wiki-merge', 'wiki-query', 'wiki-research', 'wiki-update')
MANIFEST = 'skill-version.json'
REPOSITORY = 'mesilov/pdlc-llm-wiki4sdlc-skill'


def check_destination(path: Path, root: Path, *, alias=False):
    """Reject unsafe lexical paths and symlinks before accessing project files."""
    path, root = path.absolute(), root.absolute()
    if '..' in path.parts or '..' in root.parts or not path.is_relative_to(root):
        raise ValueError(f'Конфликт: путь вне проекта: {path}')
    current = path.parent if alias else path
    while True:
        if current.is_symlink():
            raise ValueError(f'Конфликт: запись через symlink запрещена: {current}')
        if (current != path or current == root) and current.exists() and not current.is_dir():
            raise ValueError(f'Конфликт: родитель не является каталогом: {current}')
        if current == root:
            return
        if not current.is_relative_to(root):
            raise ValueError(f'Конфликт: путь вне проекта: {path}')
        current = current.parent


def source_files(directory: Path, root: Path):
    check_destination(directory, root)
    if not directory.is_dir():
        raise ValueError(f'Неполный комплект: {directory.relative_to(root)}')
    files = []
    for path in sorted(directory.rglob('*')):
        check_destination(path, root)
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        if path.is_file():
            files.append(path)
        elif not path.is_dir():
            raise ValueError(f'Недопустимый ресурс комплекта: {path.relative_to(root)}')
    return files


def required_resources():
    required = [Path('skills') / name / 'SKILL.md' for name in SKILLS]
    required.extend(Path('skills/wiki-query/references') / name for name in (
        'contract.md', 'profile.md', 'glossary.md', 'pdlc.md', 'writing.md',
        'traceability.md', 'metadata.md'))
    required.extend(Path('skills/wiki-query/references/utr-source') / name for name in (
        'skills/simple-russian/SKILL.source.md',
        'skills/simple-russian/references/checklist.md',
        'skills/simple-russian/references/use-cases.md',
        'examples/before-after-ru.md', 'examples/before-after.md',
        'evals/utr_lint.py', 'evals/md_blocks.py', 'LICENSE', 'manifest.json'))
    required.extend(Path('bin/wiki') / name for name in (
        '_core.py', '_trace.py', '_doctor.py', '_forge.py', 'lint', 'status', 'find-orphans', 'affected', 'trace', 'doctor',
        '_kit.py', '_update.py', 'update'))
    return required


def kit_files(kit: Path) -> dict[str, tuple[bytes, int]]:
    """Read only resources installed as skills and CLI, never project data."""
    for relative in required_resources():
        source = kit / relative
        check_destination(source, kit)
        if not source.is_file():
            raise ValueError(f'Неполный комплект: {relative}')
    files = {}
    trees = [(kit / 'skills' / name, Path('.agents/skills') / name) for name in SKILLS]
    trees.append((kit / 'bin/wiki', Path('bin/wiki')))
    for folder, destination in trees:
        for source in source_files(folder, kit):
            relative = (destination / source.relative_to(folder)).as_posix()
            files[relative] = source.read_bytes(), stat.S_IMODE(source.stat().st_mode)
    return files


def managed_path(value):
    if not isinstance(value, str) or '\\' in value or '\x00' in value:
        return False
    path = PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value or
            any(part in ('', '.', '..', '__pycache__') for part in path.parts) or
            path.suffix == '.pyc'):
        return False
    return ((len(path.parts) >= 3 and path.parts[:2] == ('bin', 'wiki')) or
            (len(path.parts) >= 4 and path.parts[:2] == ('.agents', 'skills') and
             path.parts[2] in SKILLS))


def validate_manifest(manifest):
    invalid = 'Недопустимый skill-version.json'
    if not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError(invalid + ': версия схемы')
    repository = manifest.get('repository')
    if not isinstance(repository, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError(invalid + ': repository')
    if manifest.get('channel') not in ('main', 'release'):
        raise ValueError(invalid + ': channel')
    commit = manifest.get('commit')
    if 'commit' not in manifest or (commit is not None and
                                   (not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit))):
        raise ValueError(invalid + ': commit')
    version = manifest.get('version')
    if 'version' not in manifest or (version is not None and
                                    (not isinstance(version, str) or not version or
                                     any(ord(char) < 32 for char in version))):
        raise ValueError(invalid + ': version')
    if type(manifest.get('source_dirty')) is not bool:
        raise ValueError(invalid + ': source_dirty')
    if manifest['source_dirty'] and commit is not None:
        raise ValueError(invalid + ': изменённый источник не имеет подтверждённого commit')
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError(invalid + ': files')
    for relative, digest in files.items():
        if not managed_path(relative) or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError(invalid + f': ресурс {relative!r}')
    if 'modes' in manifest:
        modes = manifest['modes']
        if not isinstance(modes, dict) or modes.keys() != files.keys():
            raise ValueError(invalid + ': modes должны соответствовать files')
        if any(type(mode) is not int or not 0 <= mode <= 0o7777 for mode in modes.values()):
            raise ValueError(invalid + ': права файла')
    return manifest


def make_manifest(files, repository, channel, commit, version=None, source_dirty=False) -> dict:
    manifest = {
        'schema_version': 1,
        'repository': repository,
        'channel': channel,
        'commit': commit,
        'version': version,
        'source_dirty': source_dirty,
        'files': {relative: hashlib.sha256(data).hexdigest()
                  for relative, (data, _mode) in sorted(files.items())},
        'modes': {relative: mode for relative, (_data, mode) in sorted(files.items())},
    }
    return validate_manifest(manifest)


def manifest_bytes(manifest) -> bytes:
    return (json.dumps(validate_manifest(manifest), ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def read_manifest(root: Path) -> dict | None:
    path = root / MANIFEST
    check_destination(path, root)
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError('Недопустимый skill-version.json: не является файлом')
    try:
        manifest = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as error:
        raise ValueError(f'Недопустимый skill-version.json: {error}') from error
    validate_manifest(manifest)
    for relative in manifest['files']:
        check_destination(root / relative, root)
    return manifest


def source_identity(kit: Path) -> dict:
    unknown = {'commit': None, 'version': None, 'source_dirty': False}

    def git(*args, strip=True):
        result = subprocess.run(['git', '-C', str(kit), *args], capture_output=True, text=True,
                                timeout=10, check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip() if strip else result.stdout

    try:
        top = git('rev-parse', '--show-toplevel')
        if top is None or Path(top).resolve() != kit.resolve():
            return unknown
        status = git('status', '--porcelain', '-z', '--ignored', '--untracked-files=all', '--',
                     'skills', 'bin/wiki', strip=False)
        if status is None:
            return unknown
        # Runtime Python caches do not affect the distributed kit.
        records = iter(status.split('\x00'))
        paths = []
        for record in records:
            if not record:
                continue
            paths.append(Path(record[3:]))
            if 'R' in record[:2] or 'C' in record[:2]:
                paths.append(Path(next(records, '')))
        dirty = any('__pycache__' not in path.parts and path.suffix != '.pyc' for path in paths)
        if dirty:
            return {'commit': None, 'version': None, 'source_dirty': True}
        commit = git('rev-parse', 'HEAD')
        if commit is None or not re.fullmatch(r'[0-9a-f]{40}', commit):
            return unknown
        return {'commit': commit, 'version': git('describe', '--tags', '--exact-match', 'HEAD'),
                'source_dirty': False}
    except (OSError, subprocess.TimeoutExpired):
        return unknown
