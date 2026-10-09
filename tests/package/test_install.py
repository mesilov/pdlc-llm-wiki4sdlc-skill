import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.target = Path(self.temp.name) / 'target'
        self.target.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def install(self, *args, kit=ROOT):
        return subprocess.run([sys.executable, str(kit / 'scripts/install.py'), str(self.target), *args],
                              capture_output=True, text=True)

    def copy_kit(self, name='relocated kit'):
        kit = Path(self.temp.name) / name
        for directory in ('scripts', 'skills', 'bin', 'templates'):
            shutil.copytree(ROOT / directory, kit / directory, ignore=shutil.ignore_patterns('__pycache__'))
        return kit

    def git(self, kit, *args):
        result = subprocess.run(['git', '-C', str(kit), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def committed_kit(self):
        kit = self.copy_kit()
        self.git(kit, 'init', '-q')
        self.git(kit, 'add', '.')
        self.git(kit, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '-qm', 'fixture')
        return kit

    def test_manifest_tracks_complete_kit_without_corpus_or_project_config(self):
        result = self.install('--init-wiki')
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest_path = self.target / 'skill-version.json'
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest['schema_version'], 1)
        self.assertEqual(manifest['repository'], 'mesilov/pdlc-llm-wiki4sdlc-skill')
        self.assertEqual(manifest['channel'], 'main')
        managed = manifest['files']
        for command in ('_kit.py', '_update.py', 'update'):
            self.assertIn(f'bin/wiki/{command}', managed)
        self.assertEqual(sum(path.endswith('/SKILL.md') for path in managed), 8)
        for relative, digest in managed.items():
            self.assertEqual(digest, hashlib.sha256((self.target / relative).read_bytes()).hexdigest())
            self.assertTrue(relative.startswith(('.agents/skills/wiki-', 'bin/wiki/')), relative)
            self.assertNotIn('__pycache__', relative)
        self.assertNotIn('wiki.config.json', managed)
        self.assertFalse(any(path.startswith(('raw/', 'knowledge/')) for path in managed))

    def test_manifest_is_installed_without_corpus_and_preserves_channel(self):
        kit = self.copy_kit()
        result = self.install('--channel', 'release', kit=kit)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.target / 'skill-version.json'
        self.assertEqual(json.loads(manifest.read_text())['channel'], 'release')
        before = manifest.stat().st_mtime_ns
        result = self.install(kit=kit)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(manifest.read_text())['channel'], 'release')
        self.assertEqual(manifest.stat().st_mtime_ns, before)
        self.assertFalse((self.target / 'wiki.config.json').exists())

    def test_gitless_kit_does_not_claim_an_ancestor_git_commit(self):
        kit = self.copy_kit()
        ancestor = Path(self.temp.name)
        self.git(ancestor, 'init', '-q')
        (ancestor / 'unrelated.txt').write_text('unrelated\n')
        self.git(ancestor, 'add', 'unrelated.txt')
        self.git(ancestor, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '-qm', 'unrelated')
        result = self.install(kit=kit)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.target / 'skill-version.json').is_file())
        manifest = json.loads((self.target / 'skill-version.json').read_text())
        self.assertIsNone(manifest['commit'])
        self.assertIsNone(manifest['version'])
        self.assertFalse(manifest['source_dirty'])

    def test_clean_kit_records_commit_and_exact_release_tag(self):
        kit = self.committed_kit()
        self.git(kit, 'tag', 'v2.0.0')
        (kit / 'notes.txt').write_text('untracked project notes\n')
        result = self.install(kit=kit)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.target / 'skill-version.json').is_file())
        manifest = json.loads((self.target / 'skill-version.json').read_text())
        self.assertEqual(manifest['commit'], self.git(kit, 'rev-parse', 'HEAD'))
        self.assertEqual(manifest['version'], 'v2.0.0')
        self.assertFalse(manifest['source_dirty'])

    def test_dirty_managed_source_has_unknown_commit(self):
        kit = self.committed_kit()
        source = kit / 'skills/wiki-query/SKILL.md'
        source.write_text(source.read_text() + '\nLocal edit\n')
        result = self.install(kit=kit)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.target / 'skill-version.json').is_file())
        manifest = json.loads((self.target / 'skill-version.json').read_text())
        self.assertIsNone(manifest['commit'])
        self.assertIsNone(manifest['version'])
        self.assertTrue(manifest['source_dirty'])

    def test_managed_file_with_cache_word_in_name_still_marks_source_dirty(self):
        kit = self.committed_kit()
        (kit / 'skills/wiki-query/references/__pycache__-notes.md').write_text('actual resource\n')
        result = self.install(kit=kit)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((self.target / 'skill-version.json').read_text())
        self.assertIsNone(manifest['commit'])
        self.assertTrue(manifest['source_dirty'])

    def test_ignored_managed_resources_do_not_claim_clean_commit(self):
        kit = self.committed_kit()
        (kit / '.gitignore').write_text('*.bin\nignored-assets/\n__pycache__/\n*.pyc\n')
        self.git(kit, 'add', '.gitignore')
        self.git(kit, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '-qm', 'ignore policy')
        resource = kit / 'skills/wiki-query/references/ignored.bin'
        resource.write_bytes(b'local ignored resource\x00')
        folder = kit / 'skills/wiki-query/references/ignored-assets'
        folder.mkdir()
        (folder / 'notes.md').write_text('local ignored directory resource\n')
        self.assertEqual(self.git(kit, 'status', '--porcelain'), '')
        result = self.install(kit=kit)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.target / '.agents/skills/wiki-query/references/ignored.bin').read_bytes(),
                         resource.read_bytes())
        manifest = json.loads((self.target / 'skill-version.json').read_text())
        self.assertIsNone(manifest['commit'])
        self.assertIsNone(manifest['version'])
        self.assertTrue(manifest['source_dirty'])

    def test_ignored_python_caches_do_not_mark_source_dirty_or_get_installed(self):
        kit = self.committed_kit()
        (kit / '.gitignore').write_text('__pycache__/\n*.pyc\n')
        self.git(kit, 'add', '.gitignore')
        self.git(kit, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '-qm', 'ignore caches')
        cache = kit / 'bin/wiki/__pycache__'
        cache.mkdir()
        (cache / '_kit.cpython.pyc').write_bytes(b'cache')
        (kit / 'skills/wiki-query/cache.pyc').write_bytes(b'cache')
        result = self.install(kit=kit)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((self.target / 'skill-version.json').read_text())
        self.assertEqual(manifest['commit'], self.git(kit, 'rev-parse', 'HEAD'))
        self.assertFalse(manifest['source_dirty'])
        self.assertFalse((self.target / 'bin/wiki/__pycache__').exists())
        self.assertFalse((self.target / '.agents/skills/wiki-query/cache.pyc').exists())

    def test_install_without_git_records_unknown_source_and_keeps_binary_and_modes(self):
        kit = self.copy_kit()
        binary = kit / 'skills/wiki-query/references/resource.bin'
        binary.write_bytes(b'\x00\xff\x10\x80')
        binary.chmod(0o640)
        result = subprocess.run([sys.executable, str(kit / 'scripts/install.py'), str(self.target)],
                                capture_output=True, text=True, env=dict(os.environ, PATH=''))
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.target / '.agents/skills/wiki-query/references/resource.bin'
        self.assertEqual(installed.read_bytes(), binary.read_bytes())
        self.assertEqual(installed.stat().st_mode & 0o777, 0o640)
        self.assertEqual((self.target / 'bin/wiki/update').stat().st_mode & 0o777,
                         (kit / 'bin/wiki/update').stat().st_mode & 0o777)
        self.assertTrue(os.access(self.target / 'bin/wiki/update', os.X_OK))
        manifest = json.loads((self.target / 'skill-version.json').read_text())
        self.assertIsNone(manifest['commit'])

    def test_missing_inventory_helper_is_rejected_before_any_write(self):
        kit = self.copy_kit()
        (kit / 'bin/wiki/_kit.py').unlink()
        result = self.install(kit=kit)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('Неполный комплект', result.stderr)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_symlink_inventory_helper_is_rejected_before_execution(self):
        kit = self.copy_kit()
        helper = kit / 'bin/wiki/_kit.py'
        outside = Path(self.temp.name) / 'helper.py'
        outside.write_text("raise RuntimeError('must not execute')\n")
        helper.unlink()
        helper.symlink_to(outside)
        result = self.install(kit=kit)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('symlink', result.stderr)
        self.assertNotIn('RuntimeError', result.stderr)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_corrupt_manifest_blocks_install_before_writes(self):
        manifest = self.target / 'skill-version.json'
        for content in ('not json', json.dumps({'schema_version': 99}),
                        json.dumps({'schema_version': 1, 'repository': 'owner/repo',
                                    'channel': 'main', 'commit': None, 'version': None,
                                    'source_dirty': False, 'files': {'../outside': '0' * 64}})):
            with self.subTest(content=content):
                manifest.write_text(content)
                result = self.install('--init-wiki')
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(list(self.target.iterdir()), [manifest])
                self.assertEqual(manifest.read_text(), content)

    def test_unsafe_or_mistyped_manifest_fields_are_rejected_before_writes(self):
        valid = {'schema_version': 1, 'repository': 'mesilov/pdlc-llm-wiki4sdlc-skill',
                 'channel': 'main', 'commit': None, 'version': None,
                 'source_dirty': False, 'files': {'bin/wiki/lint': '0' * 64}}
        cases = [('schema_version', True), ('repository', 7), ('channel', 'dev'),
                 ('commit', 'v1.0.0'), ('version', 5), ('source_dirty', 'false'),
                 ('files', []), ('files', {'bin/wiki/lint': 'bad hash'}),
                 ('files', {'wiki.config.json': '0' * 64}),
                 ('files', {'.agents/skills/other/SKILL.md': '0' * 64}),
                 ('files', {'bin/wiki/../../outside': '0' * 64}),
                 ('files', {'bin/wiki//lint': '0' * 64}),
                 ('files', {'bin/wiki/__pycache__/cache.pyc': '0' * 64})]
        manifest = self.target / 'skill-version.json'
        for field, value in cases:
            with self.subTest(field=field, value=value):
                content = json.dumps(dict(valid, **{field: value}))
                manifest.write_text(content)
                result = self.install('--init-wiki')
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(list(self.target.iterdir()), [manifest])
                self.assertEqual(manifest.read_text(), content)

    def test_symlink_manifest_blocks_install_before_writes(self):
        outside = Path(self.temp.name) / 'outside.json'
        outside.write_text('local file\n')
        manifest = self.target / 'skill-version.json'
        manifest.symlink_to(outside)
        result = self.install('--init-wiki')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(list(self.target.iterdir()), [manifest])
        self.assertEqual(outside.read_text(), 'local file\n')

    def test_symlink_source_is_rejected_before_any_write(self):
        kit = self.copy_kit()
        original = kit / 'skills/wiki-query/SKILL.md'
        outside = Path(self.temp.name) / 'outside-source.md'
        outside.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(outside)
        result = self.install('--init-wiki', kit=kit)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_dry_run_does_not_write(self):
        result = self.install('--init-wiki', '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertIn('wiki-query/SKILL.md', result.stdout)

    def test_init_and_all_commands_without_openspec(self):
        result = self.install('--init-wiki', '--claude')
        self.assertEqual(result.returncode, 0, result.stderr)
        skills = self.target / '.agents/skills'
        self.assertEqual(len(list(skills.glob('wiki-*/SKILL.md'))), 8)
        for name in ('glossary.md', 'pdlc.md', 'writing.md', 'traceability.md', 'metadata.md'):
            reference = Path('wiki-query/references') / name
            self.assertEqual((skills / reference).read_bytes(), (ROOT / 'skills' / reference).read_bytes())
        source = ROOT / 'skills/wiki-query/references/utr-source'
        for path in source.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                reference = Path('wiki-query/references/utr-source') / path.relative_to(source)
                self.assertEqual((skills / reference).read_bytes(), path.read_bytes())
        for skill in skills.iterdir():
            alias = self.target / '.claude/skills' / skill.name
            self.assertTrue(alias.is_symlink())
            self.assertEqual(alias.resolve(), skill.resolve())
        self.assertFalse((self.target / 'openspec').exists())
        trace = subprocess.run([sys.executable, str(self.target / 'bin/wiki/trace')],
                               cwd=self.target, capture_output=True, text=True)
        self.assertEqual(trace.returncode, 2)
        self.assertIn('подключите OpenSpec', trace.stderr)
        for command, args in [('lint', ['--dry-run']), ('status', []), ('find-orphans', []), ('affected', ['Каноническая'])]:
            with self.subTest(command=command):
                run = subprocess.run([sys.executable, str(self.target / 'bin/wiki' / command), *args],
                                     cwd=self.target, capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                if command == 'lint':
                    self.assertIn('Предупреждения: 0', run.stdout)

    def test_identical_reinstall_preserves_mtime(self):
        self.assertEqual(self.install('--init-wiki', '--claude').returncode, 0)
        before = {p: p.stat().st_mtime_ns for p in self.target.rglob('*') if p.is_file()}
        result = self.install('--init-wiki', '--claude')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in self.target.rglob('*') if p.is_file()})

    def test_installed_trace_is_read_only_on_first_run(self):
        from tests.wiki_harness.test_trace import TraceTest

        fixture = TraceTest()
        fixture.setUp()
        try:
            self.target = fixture.root
            self.assertEqual(self.install().returncode, 0)
            before = {p: p.read_bytes() for p in self.target.rglob('*') if p.is_file()}
            result = subprocess.run([str(self.target / 'bin/wiki/trace'), 'demo', '--json'],
                                    cwd=self.target, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)['features'][0]['reverse']['WK-S1'], ['OS-S1'])
            after = {p: p.read_bytes() for p in self.target.rglob('*') if p.is_file()}
            self.assertEqual(set(before), set(after))
            for path in before:
                self.assertEqual(before[path], after[path], str(path))
        finally:
            fixture.tearDown()

    def test_conflict_refuses_entire_install_and_preserves_project(self):
        entry = self.target / 'bin/wiki/lint'
        entry.parent.mkdir(parents=True)
        entry.write_text('local tool\n')
        (self.target / 'AGENTS.md').write_text('local policy\n')
        result = self.install('--init-wiki')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(entry.read_text(), 'local tool\n')
        self.assertFalse((self.target / '.agents').exists())
        self.assertFalse((self.target / 'knowledge').exists())
        self.assertEqual((self.target / 'AGENTS.md').read_text(), 'local policy\n')

    def test_refuses_symlink_destination_without_writing_outside(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (self.target / '.agents').symlink_to(outside, target_is_directory=True)
        result = self.install('--init-wiki')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.target / 'knowledge').exists())

    def test_install_into_existing_custom_corpus_keeps_config(self):
        config = {'knowledge_root': 'docs/wiki', 'raw_root': 'docs/evidence', 'openspec_root': None}
        (self.target / 'wiki.config.json').write_text(json.dumps(config))
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.target / 'wiki.config.json').read_text()), config)
        self.assertFalse((self.target / 'knowledge').exists())

    def test_relocated_kit_has_no_source_checkout_dependency(self):
        kit = Path(self.temp.name) / 'relocated kit'
        for directory in ('scripts', 'skills', 'bin', 'templates'):
            shutil.copytree(ROOT / directory, kit / directory, ignore=shutil.ignore_patterns('__pycache__'))
        result = self.install('--init-wiki', kit=kit)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, str(self.target / 'bin/wiki/lint'), '--dry-run'],
                                cwd=self.target, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_glossary_reference_is_rejected_before_any_write(self):
        kit = Path(self.temp.name) / 'incomplete glossary kit'
        for directory in ('scripts', 'skills', 'bin', 'templates'):
            shutil.copytree(ROOT / directory, kit / directory, ignore=shutil.ignore_patterns('__pycache__'))
        (kit / 'skills/wiki-query/references/glossary.md').unlink(missing_ok=True)
        result = self.install('--init-wiki', kit=kit)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('Неполный комплект', result.stderr)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_missing_pdlc_reference_is_rejected_before_any_write(self):
        kit = Path(self.temp.name) / 'incomplete pdlc kit'
        for directory in ('scripts', 'skills', 'bin', 'templates'):
            shutil.copytree(ROOT / directory, kit / directory, ignore=shutil.ignore_patterns('__pycache__'))
        (kit / 'skills/wiki-query/references/pdlc.md').unlink(missing_ok=True)
        result = self.install('--init-wiki', kit=kit)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('Неполный комплект', result.stderr)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_missing_metadata_reference_is_rejected_before_any_write(self):
        kit = Path(self.temp.name) / 'incomplete metadata kit'
        for directory in ('scripts', 'skills', 'bin', 'templates'):
            shutil.copytree(ROOT / directory, kit / directory, ignore=shutil.ignore_patterns('__pycache__'))
        (kit / 'skills/wiki-query/references/metadata.md').unlink(missing_ok=True)
        result = self.install('--init-wiki', kit=kit)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('Неполный комплект', result.stderr)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_missing_writing_reference_is_rejected_before_any_write(self):
        kit = Path(self.temp.name) / 'incomplete writing kit'
        for directory in ('scripts', 'skills', 'bin', 'templates'):
            shutil.copytree(ROOT / directory, kit / directory, ignore=shutil.ignore_patterns('__pycache__'))
        (kit / 'skills/wiki-query/references/writing.md').unlink(missing_ok=True)
        result = self.install('--init-wiki', kit=kit)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('Неполный комплект', result.stderr)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_missing_trace_resources_are_rejected_before_any_write(self):
        kit = Path(self.temp.name) / 'incomplete trace kit'
        for directory in ('scripts', 'skills', 'bin', 'templates'):
            shutil.copytree(ROOT / directory, kit / directory, ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('bin/wiki/_trace.py', 'bin/wiki/trace', 'skills/wiki-query/references/traceability.md'):
            with self.subTest(resource=name):
                path = kit / name
                original = path.read_bytes()
                path.unlink()
                result = self.install('--init-wiki', kit=kit)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('Неполный комплект', result.stderr)
                self.assertEqual(list(self.target.iterdir()), [])
                path.write_bytes(original)

    def test_missing_utr_source_resource_is_rejected_before_any_write(self):
        kit = Path(self.temp.name) / 'incomplete utr source kit'
        for directory in ('scripts', 'skills', 'bin', 'templates'):
            shutil.copytree(ROOT / directory, kit / directory, ignore=shutil.ignore_patterns('__pycache__'))
        resources = (
            'skills/simple-russian/SKILL.source.md',
            'skills/simple-russian/references/checklist.md',
            'skills/simple-russian/references/use-cases.md',
            'examples/before-after-ru.md', 'examples/before-after.md',
            'evals/utr_lint.py', 'evals/md_blocks.py', 'LICENSE', 'manifest.json',
        )
        for name in resources:
            with self.subTest(resource=name):
                path = kit / 'skills/wiki-query/references/utr-source' / name
                original = path.read_bytes() if path.exists() else None
                path.unlink(missing_ok=True)
                result = self.install('--init-wiki', kit=kit)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('Неполный комплект', result.stderr)
                self.assertEqual(list(self.target.iterdir()), [])
                if original is not None:
                    path.write_bytes(original)

    def test_incomplete_kit_is_rejected_before_any_write(self):
        kit = Path(self.temp.name) / 'incomplete kit'
        for directory in ('scripts', 'skills', 'bin', 'templates'):
            shutil.copytree(ROOT / directory, kit / directory, ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('bin/wiki/_core.py', 'bin/wiki/lint',
                     'bin/wiki/_update.py', 'bin/wiki/update',
                     'skills/wiki-query/references/contract.md',
                     'skills/wiki-query/references/profile.md',
                     'templates/wiki/knowledge/SCHEMA.md'):
            with self.subTest(resource=name):
                path = kit / name
                original = path.read_bytes()
                path.unlink()
                result = self.install('--init-wiki', kit=kit)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('Неполный комплект', result.stderr)
                self.assertEqual(list(self.target.iterdir()), [])
                path.write_bytes(original)

    def test_doctor_is_installed_executable_and_read_only(self):
        import os

        self.assertEqual(self.install('--init-wiki').returncode, 0)
        doctor = self.target / 'bin/wiki/doctor'
        self.assertTrue(os.access(doctor, os.X_OK))
        self.assertTrue((self.target / 'bin/wiki/_doctor.py').is_file())
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.target.rglob('*') if p.is_file()}
        env = {**os.environ, 'HOME': str(self.target.parent / 'empty-home'),
               'CODEX_HOME': str(self.target.parent / 'empty-codex'),
               'XDG_CONFIG_HOME': str(self.target.parent / 'empty-config'), 'PATH': ''}
        result = subprocess.run([sys.executable, str(doctor), '--json'],
                                cwd=self.target, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['exit_code'], 0)
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.target.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_missing_doctor_files_block_install_before_any_write(self):
        kit = Path(self.temp.name) / 'incomplete doctor kit'
        for directory in ('scripts', 'skills', 'bin', 'templates'):
            shutil.copytree(ROOT / directory, kit / directory, ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('bin/wiki/doctor', 'bin/wiki/_doctor.py'):
            with self.subTest(resource=name):
                path = kit / name
                original = path.read_bytes()
                path.unlink()
                result = self.install('--init-wiki', kit=kit)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('Неполный комплект', result.stderr)
                self.assertEqual(list(self.target.iterdir()), [])
                path.write_bytes(original)
