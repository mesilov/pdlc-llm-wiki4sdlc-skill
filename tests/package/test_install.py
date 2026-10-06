import json
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
        for name in ('glossary.md', 'pdlc.md', 'writing.md', 'traceability.md'):
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
