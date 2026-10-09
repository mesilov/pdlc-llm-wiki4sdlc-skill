"""Check GitHub and transactionally update the installed wiki kit."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

from _kit import (MANIFEST, REPOSITORY, SKILLS, check_destination, kit_files,
                  make_manifest, manifest_bytes, read_manifest)

API = 'https://api.github.com/repos/'
MAX_DOWNLOAD = 20 * 1024 * 1024
MAX_UNPACKED = 64 * 1024 * 1024
SHA = re.compile(r'[0-9a-f]{40}')


def fetch(url: str, *, limit: int, timeout: int = 10) -> bytes:
    request = Request(url, headers={'Accept': 'application/vnd.github+json',
                                   'User-Agent': 'pdlc-wiki-kit-updater'})
    with urlopen(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Ответ GitHub превышает допустимый размер')
    return data


def github_json(url: str) -> dict:
    value = json.loads(fetch(url, limit=1024 * 1024))
    if not isinstance(value, dict):
        raise ValueError('Неверный JSON object в ответе GitHub')
    return value


def remote_revision(repository: str, channel: str) -> dict:
    base = API + repository
    version = None
    ref = 'main'
    if channel == 'release':
        try:
            release = github_json(base + '/releases/latest')
        except HTTPError as error:
            if error.code == 404:
                raise ValueError('Стабильный релиз GitHub не найден; выберите --channel main явно') from error
            raise
        ref = version = release.get('tag_name')
        if (not isinstance(ref, str) or not ref.strip() or
                release.get('draft') or release.get('prerelease')):
            raise ValueError('GitHub не вернул опубликованный стабильный релиз')
    commit = github_json(base + '/commits/' + quote(ref, safe='')).get('sha')
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        raise ValueError('GitHub не вернул корректный commit SHA')
    url = f'https://github.com/{repository}/commit/{commit}'
    if version:
        url = f'https://github.com/{repository}/releases/tag/{quote(version, safe="")}'
    return {'repository': repository, 'channel': channel, 'commit': commit,
            'version': version, 'url': url}


def managed_source(path: PurePosixPath) -> bool:
    parts = path.parts
    return ((len(parts) >= 3 and parts[0] == 'skills' and parts[1] in SKILLS) or
            (len(parts) >= 3 and parts[:2] == ('bin', 'wiki')))


def unpack_archive(data: bytes, destination: Path) -> None:
    """Extract only resource files, never upstream code outside the kit."""
    seen = set()
    prefix = None
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for count, entry in enumerate(archive, 1):
            total += entry.size
            if count > 10000 or total > MAX_UNPACKED:
                raise ValueError('Архив комплекта превышает допустимый размер')
            path = PurePosixPath(entry.name)
            if (path.is_absolute() or '..' in path.parts or '\\' in entry.name or
                    not path.parts or entry.size < 0):
                raise ValueError('Небезопасный путь в архиве комплекта')
            if prefix is None:
                prefix = path.parts[0]
            if path.parts[0] != prefix:
                raise ValueError('Архив имеет несколько корней')
            relative = PurePosixPath(*path.parts[1:])
            if not managed_source(relative):
                continue
            if entry.isdir():
                continue
            if not entry.isfile():
                raise ValueError(f'symlink или специальный файл в архиве: {relative}')
            if relative in seen:
                raise ValueError(f'Повторный файл в архиве: {relative}')
            seen.add(relative)
            stream = archive.extractfile(entry)
            if stream is None:
                raise ValueError(f'Не удалось прочитать ресурс: {relative}')
            content = stream.read(MAX_UNPACKED + 1)
            if len(content) != entry.size:
                raise ValueError(f'Неполный ресурс в архиве: {relative}')
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(0o755 if entry.mode & 0o111 else 0o644)


def download_files(available: dict) -> dict:
    url = API + available['repository'] + '/tarball/' + available['commit']
    archive = fetch(url, limit=MAX_DOWNLOAD, timeout=20)
    with tempfile.TemporaryDirectory(prefix='wiki-kit-') as folder:
        kit = Path(folder)
        unpack_archive(archive, kit)
        return kit_files(kit)


def atomic_write(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.wiki-kit-', delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def current_file(path: Path, root: Path) -> tuple[bytes, int] | None:
    check_destination(path, root)
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f'Конфликт: путь не является обычным файлом: {path.relative_to(root)}')
    return path.read_bytes(), stat.S_IMODE(path.stat().st_mode)


def update_plan(root: Path, files: dict, installed: dict | None, force: bool) -> tuple[dict, dict]:
    previous = installed['files'] if installed else {}
    modes = installed.get('modes', {}) if installed else {}
    changes, originals = {}, {}
    for name in sorted(set(previous) | set(files)):
        original = current_file(root / name, root)
        desired = files.get(name)
        if original == desired:
            continue
        if original is not None:
            digest = hashlib.sha256(original[0]).hexdigest()
            # Older manifests lack modes: refuse an unverified mode change or
            # deletion rather than silently replacing access restrictions.
            baseline_mode = modes.get(name)
            if baseline_mode is None and desired is not None:
                baseline_mode = desired[1]
            if (digest != previous.get(name) or original[1] != baseline_mode) and not force:
                raise ValueError(f'Конфликт: локально изменённый файл {name}; '
                                 'для замены с backup используйте --force')
        changes[name], originals[name] = desired, original
    return changes, originals


def apply_update(root: Path, changes: dict, originals: dict, manifest: dict) -> Path | None:
    metadata = current_file(root / MANIFEST, root)
    new_metadata = manifest_bytes(manifest), 0o644
    if metadata == new_metadata and not changes:
        return None
    changes = dict(changes)
    originals = dict(originals)
    # The installed revision changes only after all resource writes succeed.
    changes[MANIFEST], originals[MANIFEST] = new_metadata, metadata
    backup = None
    if any(value is not None for value in originals.values()):
        backup = root / '.wiki-kit-backups' / uuid4().hex
        check_destination(backup, root)
        backup.mkdir(parents=True)
        for name, original in originals.items():
            if original is not None:
                target = backup / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original[0])
                target.chmod(original[1])
    completed = []
    try:
        # Refuse a changed preflight snapshot before replacing anything.
        for name, original in originals.items():
            if current_file(root / name, root) != original:
                raise ValueError(f'Файл изменился во время подготовки: {name}')
        for name, desired in changes.items():
            target = root / name
            check_destination(target, root)
            completed.append(name)
            if desired is None:
                target.unlink(missing_ok=True)
            else:
                atomic_write(target, *desired)
    except (OSError, ValueError) as error:
        failures = []
        for name in reversed(completed):
            try:
                check_destination(root / name, root)
                original = originals[name]
                if original is None:
                    (root / name).unlink(missing_ok=True)
                else:
                    atomic_write(root / name, *original)
            except (OSError, ValueError) as restore_error:
                failures.append(str(restore_error))
        detail = f'; backup: {backup}' if backup else ''
        if failures:
            detail += '; восстановление требует проверки: ' + '; '.join(failures)
        raise ValueError(f'Обновление не выполнено: {error}{detail}') from error
    return backup


def project_root(project: Path | None) -> Path:
    if project is not None:
        root = project.resolve()
    else:
        current = Path.cwd().resolve()
        root = None
        for candidate in (current, *current.parents):
            # Kit maintenance must work even with a broken/absent wiki profile.
            # Stop at a nested Git boundary before considering parent manifests.
            if any((candidate / marker).exists() or (candidate / marker).is_symlink()
                   for marker in ('.git', MANIFEST, 'wiki.config.json')):
                root = candidate
                break
        if root is None:
            raise ValueError('Не найден корень проекта; укажите целевой каталог явно')
    if not root.is_dir():
        raise ValueError(f'Каталог проекта не существует: {root}')
    if (root / 'skills/wiki-query/SKILL.md').exists() and (root / 'scripts/install.py').exists():
        raise ValueError('Обновляйте установленный комплект в отдельном целевом проекте')
    return root


def print_check(result: dict) -> None:
    installed = result['installed']
    if installed is None or not installed['commit']:
        print('Текущая версия: неизвестна (старая или локально изменённая установка)')
    else:
        print(f'Текущая версия: {installed.get("version") or installed["commit"]}')
    remote = result['available']
    print(f'Доступная версия ({remote["channel"]}): {remote["version"] or remote["commit"]}')
    print(remote['url'])
    if result.get('compare_url'):
        print('Сравнение: ' + result['compare_url'])
    if result['update_available']:
        print('Доступно обновление. Запустите bin/wiki/update для подтверждения '
              f'(--channel {remote["channel"]}).')
    else:
        print('Установлена актуальная версия выбранного канала.')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', nargs='?', type=Path, help='destination project; default: current checkout')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check', action='store_true', help='read-only check for updates')
    modes.add_argument('--force', action='store_true', help='reinstall without confirmation; back up local edits')
    parser.add_argument('--channel', choices=('main', 'release'), help='update source; defaults to saved channel or main')
    parser.add_argument('--json', action='store_true', help='machine-readable check result (requires --check)')
    args = parser.parse_args(argv)
    if args.json and not args.check:
        parser.error('--json requires --check')
    try:
        root = project_root(args.project)
        installed = read_manifest(root)
        repository = installed['repository'] if installed else REPOSITORY
        channel = args.channel or (installed['channel'] if installed else 'main')
        available = remote_revision(repository, channel)
        changed = (installed is None or installed['commit'] != available['commit'] or
                   installed['source_dirty'] or installed['channel'] != channel or
                   (channel == 'release' and installed.get('version') != available['version']))
        result = {'installed': installed, 'available': available, 'update_available': changed}
        if installed and installed['commit']:
            result['compare_url'] = (f'https://github.com/{repository}/compare/'
                                     f'{installed["commit"]}...{available["commit"]}')
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print_check(result)
        if args.check:
            return 1 if changed else 0
        if not changed and not args.force:
            return 0
        if not args.force and not sys.stdin.isatty():
            print('Без терминала обновление не выполняется. Для безусловного обновления используйте --force.')
            return 1
        files = download_files(available)
        changes, originals = update_plan(root, files, installed, args.force)
        metadata = make_manifest(files, repository, channel, available['commit'], available['version'])
        if not args.force:
            print(f'План: {len(changes)} управляемых файлов; профиль и корпус сохраняются.')
            answer = input('Обновить комплект? [y/N]: ').strip().casefold()
            if answer not in {'y', 'yes', 'д', 'да'}:
                print('Обновление отменено.')
                return 1
        backup = apply_update(root, changes, originals, metadata)
        if backup:
            print('Резервная копия: ' + str(backup.relative_to(root)))
        print('Комплект обновлён: ' + available['commit'])
        return 0
    except (ValueError, OSError, URLError, tarfile.TarError, EOFError) as error:
        print(f'Ошибка обновления: {error}', file=sys.stderr)
        return 2
