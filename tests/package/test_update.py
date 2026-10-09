"""Updater acceptance tests; HTTP is the only mocked external boundary."""
import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[2]
OLD = '1' * 40
NEW = '2' * 40
RESOURCE = '.agents/skills/wiki-query/SKILL.md'


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mode & 0o777)
            for p in root.rglob('*') if p.is_file() and not p.is_symlink()
            and '.wiki-kit-backups' not in p.parts and '__pycache__' not in p.parts}


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'bin/wiki/_update.py').exists(), 'updater is not implemented')
        sys.path.insert(0, str(ROOT / 'bin/wiki'))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / 'bin/wiki')))
        spec = importlib.util.spec_from_file_location('wiki_updater_test', ROOT / 'bin/wiki/_update.py')
        self.updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.updater)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        run = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'),
                              str(self.root), '--init-wiki', '--claude'],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.manifest = self.root / 'skill-version.json'
        data = json.loads(self.manifest.read_text())
        data.update(commit=OLD, version='v1.0.0', source_dirty=False)
        self.manifest.write_text(json.dumps(data))
        self.remote = Path(self.temp.name) / 'upstream'
        self.remote.mkdir()
        for directory in ('skills', 'bin'):
            shutil.copytree(ROOT / directory, self.remote / directory,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.skill = self.remote / 'skills/wiki-query/SKILL.md'
        self.skill.write_bytes(self.skill.read_bytes() + b'\nUpstream change.\n')
        self.commit = NEW
        self.version = 'v2.0.0'
        self.calls = []
        self.extra = []

    def archive(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            archive.add(self.remote, arcname='upstream-snapshot')
            for entry, content in self.extra:
                archive.addfile(entry, io.BytesIO(content) if content is not None else None)
        return buffer.getvalue()

    def http(self, request, timeout):
        self.assertGreater(timeout, 0)
        url = request.full_url
        self.calls.append(url)
        if '/releases/latest' in url:
            return io.BytesIO(json.dumps({'tag_name': self.version, 'draft': False,
                                         'prerelease': False}).encode())
        if '/commits/' in url:
            return io.BytesIO(json.dumps({'sha': self.commit}).encode())
        if '/tarball/' in url:
            self.assertTrue(url.endswith('/' + self.commit), url)
            return io.BytesIO(self.archive())
        self.fail('unexpected HTTP request: ' + url)

    def run_update(self, *args, answer=None, http=None, default_root=False):
        output, error = io.StringIO(), io.StringIO()
        stdin = io.StringIO(answer or '')
        with patch.object(stdin, 'isatty', return_value=answer is not None), \
             patch.object(sys, 'stdin', stdin), \
             patch.object(self.updater, 'urlopen', side_effect=http or self.http), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = self.updater.main([*([str(self.root)] if not default_root else []), *args])
        return code, output.getvalue(), error.getvalue()

    def test_check_reports_main_change_without_any_target_write(self):
        before = snapshot(self.root)
        code, output, error = self.run_update('--check', '--json')
        self.assertEqual(code, 1, error)
        data = json.loads(output)
        self.assertTrue(data['update_available'])
        self.assertEqual(data['installed']['commit'], OLD)
        self.assertEqual(data['available']['commit'], NEW)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / '.wiki-kit-backups').exists())
        self.assertFalse(any('/tarball/' in url for url in self.calls))

    def test_default_root_check_does_not_require_valid_wiki_or_knowledge(self):
        shutil.rmtree(self.root / 'knowledge')
        (self.root / 'wiki.config.json').write_text('invalid project profile')
        before = snapshot(self.root)
        with patch.object(Path, 'cwd', return_value=self.root):
            code, output, error = self.run_update('--check', '--json', default_root=True)
        self.assertEqual(code, 1, error)
        self.assertTrue(json.loads(output)['update_available'])
        self.assertEqual(snapshot(self.root), before)

    def test_nested_checkout_does_not_use_parent_install_manifest(self):
        child = self.root / 'nested'
        child.mkdir()
        (child / '.git').mkdir()
        before = snapshot(self.root)
        with patch.object(Path, 'cwd', return_value=child):
            code, output, error = self.run_update('--check', '--json', default_root=True)
        self.assertEqual(code, 1, error)
        self.assertIsNone(json.loads(output)['installed'])
        self.assertEqual(snapshot(self.root), before)

    def test_same_revision_returns_zero(self):
        self.commit = OLD
        before = snapshot(self.root)
        code, output, error = self.run_update('--check', '--json')
        self.assertEqual(code, 0, error)
        self.assertFalse(json.loads(output)['update_available'])
        self.assertEqual(snapshot(self.root), before)

    def test_stable_major_release_resolves_tag_to_exact_commit(self):
        code, output, error = self.run_update('--check', '--json', '--channel', 'release')
        self.assertEqual(code, 1, error)
        data = json.loads(output)
        self.assertEqual(data['available']['version'], 'v2.0.0')
        self.assertEqual(data['available']['commit'], NEW)
        self.assertTrue(any('/commits/v2.0.0' in url for url in self.calls))

    def test_network_failure_is_read_only_error(self):
        before = snapshot(self.root)
        def offline(request, timeout):
            raise URLError('offline')
        code, _, error = self.run_update('--check', http=offline)
        self.assertEqual(code, 2)
        self.assertIn('offline', error)
        self.assertEqual(snapshot(self.root), before)

    def test_no_release_does_not_fall_back_to_main(self):
        before = snapshot(self.root)
        def missing(request, timeout):
            self.assertIn('/releases/latest', request.full_url)
            raise HTTPError(request.full_url, 404, 'Not Found', {}, None)
        code, _, error = self.run_update('--check', '--channel', 'release', http=missing)
        self.assertEqual(code, 2)
        self.assertIn('релиз', error.casefold())
        self.assertEqual(snapshot(self.root), before)

    def test_noninteractive_update_only_proposes(self):
        before = snapshot(self.root)
        code, output, error = self.run_update()
        self.assertEqual(code, 1, error)
        self.assertIn('bin/wiki/update', output)
        self.assertEqual(snapshot(self.root), before)

    def test_decline_does_not_modify_project(self):
        before = snapshot(self.root)
        code, _, error = self.run_update(answer='нет\n')
        self.assertEqual(code, 1, error)
        self.assertEqual(snapshot(self.root), before)

    def test_consent_updates_complete_kit_and_manifest(self):
        code, _, error = self.run_update(answer='да\n')
        self.assertEqual(code, 0, error)
        self.assertEqual((self.root / RESOURCE).read_bytes(), self.skill.read_bytes())
        self.assertEqual(json.loads(self.manifest.read_text())['commit'], NEW)
        self.assertTrue((self.root / '.claude/skills/wiki-query').is_symlink())

    def test_force_updates_without_reading_stdin(self):
        with patch('builtins.input', side_effect=AssertionError('must not ask')):
            code, _, error = self.run_update('--force')
        self.assertEqual(code, 0, error)
        self.assertEqual((self.root / RESOURCE).read_bytes(), self.skill.read_bytes())

    def test_force_reinstalls_same_revision(self):
        self.commit = OLD
        code, _, error = self.run_update('--force')
        self.assertEqual(code, 0, error)
        self.assertEqual((self.root / RESOURCE).read_bytes(), self.skill.read_bytes())
        self.assertTrue(any('/tarball/' in url for url in self.calls))

    def test_local_edits_block_entire_normal_update(self):
        (self.root / RESOURCE).write_text('local skill\n')
        before = snapshot(self.root)
        code, _, error = self.run_update(answer='да\n')
        self.assertEqual(code, 2)
        self.assertIn('Конфликт', error)
        self.assertEqual(snapshot(self.root), before)

    def test_force_preserves_local_edits_in_backup(self):
        (self.root / RESOURCE).write_text('local skill\n')
        old_manifest = self.manifest.read_bytes()
        code, output, error = self.run_update('--force')
        self.assertEqual(code, 0, error)
        backups = list((self.root / '.wiki-kit-backups').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / RESOURCE).read_text(), 'local skill\n')
        self.assertEqual((backups[0] / 'skill-version.json').read_bytes(), old_manifest)
        self.assertIn('.wiki-kit-backups', output)

    def test_profile_corpus_policies_and_unknown_files_are_preserved(self):
        (self.root / 'wiki.config.json').write_text('{"language":"en","knowledge_root":"docs/wiki"}\n')
        (self.root / 'knowledge/domains').mkdir()
        (self.root / 'knowledge/domains/custom.md').write_text('authored knowledge\n')
        (self.root / 'AGENTS.md').write_text('project policy\n')
        (self.root / 'bin/wiki/local-tool').write_text('project tool\n')
        (self.root / '.agents/skills/wiki-query/local.md').write_text('custom skill reference\n')
        excluded = ('wiki.config.json', 'knowledge/domains/custom.md', 'AGENTS.md',
                    'bin/wiki/local-tool', '.agents/skills/wiki-query/local.md')
        before = {name: (self.root / name).read_bytes() for name in excluded}
        code, _, error = self.run_update('--force')
        self.assertEqual(code, 0, error)
        self.assertEqual(before, {name: (self.root / name).read_bytes() for name in excluded})

    def test_added_and_removed_managed_files(self):
        obsolete = self.root / 'bin/wiki/obsolete'
        obsolete.write_text('old managed\n')
        data = json.loads(self.manifest.read_text())
        import hashlib
        data['files']['bin/wiki/obsolete'] = hashlib.sha256(obsolete.read_bytes()).hexdigest()
        self.manifest.write_text(json.dumps(data))
        (self.remote / 'skills/wiki-query/references/new.md').write_text('new resource\n')
        code, _, error = self.run_update('--force')
        self.assertEqual(code, 0, error)
        self.assertFalse(obsolete.exists())
        self.assertTrue((self.root / '.agents/skills/wiki-query/references/new.md').is_file())
        self.assertNotIn('bin/wiki/obsolete', json.loads(self.manifest.read_text())['files'])

    def test_bootstrap_without_manifest_reports_unknown_version(self):
        self.manifest.unlink()
        before = snapshot(self.root)
        code, output, error = self.run_update('--check', '--json')
        self.assertEqual(code, 1, error)
        self.assertIsNone(json.loads(output)['installed'])
        self.assertEqual(snapshot(self.root), before)

    def test_force_bootstraps_legacy_installation(self):
        self.manifest.unlink()
        (self.root / RESOURCE).write_text('legacy local edit\n')
        code, _, error = self.run_update('--force')
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(self.manifest.read_text())['commit'], NEW)
        backup = next((self.root / '.wiki-kit-backups').iterdir())
        self.assertEqual((backup / RESOURCE).read_text(), 'legacy local edit\n')

    def test_dirty_source_manifest_does_not_report_current(self):
        data = json.loads(self.manifest.read_text())
        data.update(commit=None, source_dirty=True)
        self.manifest.write_text(json.dumps(data))
        code, output, error = self.run_update('--check', '--json')
        self.assertEqual(code, 1, error)
        self.assertTrue(json.loads(output)['update_available'])

    def test_selected_release_channel_persists(self):
        code, _, error = self.run_update('--channel', 'release', '--force')
        self.assertEqual(code, 0, error)
        self.calls.clear()
        code, _, error = self.run_update('--check')
        self.assertEqual(code, 0, error)
        self.assertTrue(any('/releases/latest' in url for url in self.calls))

    def test_major_version_at_same_commit_is_reported(self):
        data = json.loads(self.manifest.read_text())
        data['channel'] = 'release'
        self.manifest.write_text(json.dumps(data))
        self.commit = OLD
        code, output, error = self.run_update('--check', '--json')
        self.assertEqual(code, 1, error)
        self.assertEqual(json.loads(output)['available']['version'], 'v2.0.0')

    def test_destination_symlink_is_rejected_even_with_force(self):
        outside = Path(self.temp.name) / 'outside'
        outside.write_text('outside\n')
        (self.root / RESOURCE).unlink()
        (self.root / RESOURCE).symlink_to(outside)
        code, _, error = self.run_update('--force')
        self.assertEqual(code, 2)
        self.assertIn('symlink', error)
        self.assertEqual(outside.read_text(), 'outside\n')

    def test_backup_symlink_is_rejected_before_any_write(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (self.root / '.wiki-kit-backups').symlink_to(outside, target_is_directory=True)
        before = snapshot(self.root)
        code, _, error = self.run_update('--force')
        self.assertEqual(code, 2)
        self.assertIn('symlink', error)
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(list(outside.iterdir()), [])

    def test_incomplete_archive_is_rejected_before_writes(self):
        (self.remote / 'skills/wiki-query/references/contract.md').unlink()
        before = snapshot(self.root)
        code, _, error = self.run_update('--force')
        self.assertEqual(code, 2)
        self.assertIn('Неполный комплект', error)
        self.assertEqual(snapshot(self.root), before)

    def test_archive_traversal_is_rejected(self):
        entry = tarfile.TarInfo('upstream-snapshot/../escape')
        entry.size = 4
        self.extra = [(entry, b'evil')]
        before = snapshot(self.root)
        code, _, error = self.run_update('--force')
        self.assertEqual(code, 2)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((Path(self.temp.name) / 'escape').exists())

    def test_archive_managed_symlink_is_rejected(self):
        entry = tarfile.TarInfo('upstream-snapshot/skills/wiki-query/references/evil')
        entry.type = tarfile.SYMTYPE
        entry.linkname = '/tmp/outside'
        self.extra = [(entry, None)]
        before = snapshot(self.root)
        code, _, error = self.run_update('--force')
        self.assertEqual(code, 2)
        self.assertIn('symlink', error)
        self.assertEqual(snapshot(self.root), before)

    def test_malformed_commit_is_rejected(self):
        self.commit = '../escape'
        before = snapshot(self.root)
        code, _, _ = self.run_update('--check')
        self.assertEqual(code, 2)
        self.assertEqual(snapshot(self.root), before)

    def test_corrupt_manifest_is_not_silently_bootstrapped(self):
        self.manifest.write_text('not json')
        before = snapshot(self.root)
        code, _, _ = self.run_update('--force')
        self.assertEqual(code, 2)
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(self.calls, [])

    def test_write_error_restores_pre_update_files(self):
        before = snapshot(self.root)
        original = self.updater.atomic_write
        attempts = 0
        def fail_second(path, content, mode):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise OSError('simulated write failure')
            return original(path, content, mode)
        with patch.object(self.updater, 'atomic_write', side_effect=fail_second):
            code, _, error = self.run_update('--force')
        self.assertEqual(code, 2)
        self.assertIn('simulated write failure', error)
        self.assertEqual(snapshot(self.root), before)

    def test_installed_entrypoint_help_is_read_only_without_source_checkout(self):
        before = snapshot(self.root)
        run = subprocess.run([sys.executable, str(self.root / 'bin/wiki/update'), '--help'],
                             cwd=self.root, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('--force', run.stdout)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(list(self.root.rglob('__pycache__')))
