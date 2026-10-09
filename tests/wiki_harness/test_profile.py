import json
import os
import shutil
from pathlib import Path

from tests.wiki_harness.test_cli import WikiCliTestCase


class PortableProfileTest(WikiCliTestCase):
    def profile(self, **values):
        self.write('wiki.config.json', json.dumps(values))

    def resolved_raw_categories(self):
        import subprocess
        import sys
        from tests.wiki_harness.test_cli import BIN_DIR
        result = subprocess.run(
            [sys.executable, '-c',
             'import json; from pathlib import Path; from _core import wiki_layout; '
             'print(json.dumps(getattr(wiki_layout(Path.cwd()), "raw_categories", None)))'],
            cwd=self.root, env={**os.environ, 'PYTHONPATH': str(BIN_DIR)},
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_default_raw_categories_do_not_create_directories(self):
        before = sorted(path.relative_to(self.root) for path in self.root.rglob('*'))
        self.assertEqual(self.resolved_raw_categories(), ['sources', 'research'])
        self.profile()
        self.assertEqual(self.resolved_raw_categories(), ['sources', 'research'])
        self.assertEqual(sorted(path.relative_to(self.root) for path in self.root.rglob('*')),
                         sorted([*before, Path('wiki.config.json')]))

    def test_explicit_raw_categories_replace_defaults(self):
        for categories in (['interviews', 'experiments'], []):
            with self.subTest(categories=categories):
                self.profile(raw_categories=categories)
                self.assertEqual(self.resolved_raw_categories(), categories)

    def test_raw_defaults_preserve_legacy_materials_and_custom_root(self):
        (self.root / 'raw').rename(self.root / 'evidence')
        source = self.write('evidence/observations/capture.md', '# Observation\n')
        self.profile(raw_root='evidence')
        before = source.read_bytes()
        self.assertEqual(self.resolved_raw_categories(), ['sources', 'research'])
        result = self.run_cli('status')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse((self.root / 'raw').exists())
        self.assertFalse((self.root / 'evidence/sources').exists())

    def resolved_views(self):
        import subprocess
        import sys
        from tests.wiki_harness.test_cli import BIN_DIR
        result = subprocess.run(
            [sys.executable, '-c',
             'import json; from pathlib import Path; from _core import wiki_layout; '
             'print(json.dumps(wiki_layout(Path.cwd()).views))'],
            cwd=self.root, env={**os.environ, 'PYTHONPATH': str(BIN_DIR)},
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_default_lenses_without_materializing_pages(self):
        before = sorted(path.relative_to(self.root) for path in self.root.rglob('*'))
        self.assertEqual(self.resolved_views(), [
            'product', 'discovery', 'experience', 'engineering',
            'go-to-market', 'operations', 'measurement'])
        self.assertEqual(sorted(path.relative_to(self.root) for path in self.root.rglob('*')), before)

    def test_explicit_views_replace_lens_defaults(self):
        for views in (['research', 'operations'], []):
            with self.subTest(views=views):
                self.profile(views=views)
                self.assertEqual(self.resolved_views(), views)

    def test_views_layer_is_configurable_and_counted_without_migration(self):
        self.profile(layers={'views': 'perspectives'})
        self.write('knowledge/perspectives/product/page.md', '# Product view\n')
        self.write('knowledge/perspectives/engineering/page.md', '# Engineering view\n')
        self.write('knowledge/operations/page.md', '# Legacy view\n')
        result = self.run_cli('status')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Представление product: 1', result.stdout)
        self.assertIn('Представление engineering: 1', result.stdout)
        self.assertIn('Представление operations: 1', result.stdout)
        self.assertNotIn('Представление perspectives:', result.stdout)
        self.assertFalse((self.root / 'knowledge/views').exists())

    def test_status_counts_default_nested_views(self):
        self.write('knowledge/views/discovery/page.md', '# Discovery view\n')
        result = self.run_cli('status')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Представление discovery: 1', result.stdout)
        self.assertNotIn('Представление views:', result.stdout)

    def test_status_does_not_count_layer_ancestors_as_legacy_views(self):
        self.profile(layers={'views': 'perspectives/lenses', 'domains': 'canonical/topics'})
        self.write('knowledge/perspectives/lenses/product/page.md', '# Product\n')
        self.write('knowledge/canonical/topics/demo/page.md', '# Topic\n')
        result = self.run_cli('status')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Представление product: 1', result.stdout)
        self.assertIn('Доменные страницы: 1', result.stdout)
        self.assertNotIn('Представление perspectives:', result.stdout)
        self.assertNotIn('Представление canonical:', result.stdout)

    def relocate(self):
        (self.root / 'docs/wiki').mkdir(parents=True)
        for name in ('raw', 'knowledge'):
            (self.root / name).rename(self.root / 'docs/wiki' / name)
        (self.root / 'planning').mkdir()
        (self.root / 'openspec').rename(self.root / 'planning/openspec')
        self.profile(corpus_root='docs/wiki', openspec_root='planning/openspec')

    def test_all_commands_follow_relocated_roots(self):
        self.relocate()
        self.write('docs/wiki/raw/source.md', '# Source\n')
        self.write('docs/wiki/knowledge/domains/topic/page.md', '[Source](../../../raw/source.md)\n')
        self.write('planning/openspec/changes/example/proposal.md', '[Knowledge](../../../../docs/wiki/knowledge/domains/topic/page.md)\n')
        result = self.run_cli('lint', '--dry-run')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        affected = self.run_cli('affected', 'docs/wiki/raw/source.md')
        self.assertIn('docs/wiki/knowledge/domains/topic/page.md', affected.stdout)
        reverse = self.run_cli('affected', 'docs/wiki/knowledge/domains/topic/page.md')
        self.assertIn('planning/openspec/changes/example/proposal.md', reverse.stdout)
        self.assertEqual(self.run_cli('status').returncode, 0)
        self.assertIn('docs/wiki/knowledge/domains/topic/page.md', self.run_cli('find-orphans').stdout)

    def test_nested_cwd_finds_profile(self):
        import subprocess
        import sys
        from tests.wiki_harness.test_cli import BIN_DIR
        self.relocate()
        self.write('docs/wiki/raw/source.md', '# Source\n')
        result = subprocess.run([sys.executable, str(BIN_DIR / 'status')],
            cwd=self.root / 'docs/wiki/knowledge', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Первичные источники: 1', result.stdout)

    def test_missing_openspec_blocks_every_command_before_fix(self):
        self.profile(openspec_root='openspec')
        shutil.rmtree(self.root / 'openspec')
        glossary = self.write('knowledge/GLOSSARY.md', '# Glossary\n\n## Z\n\nZ.\n\n## A\n\nA.\n')
        before = glossary.read_bytes()
        for command, args in [('lint', ('--fix',)), ('status', ()), ('find-orphans', ()), ('affected', ('A',))]:
            with self.subTest(command=command):
                result = self.run_cli(command, *args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('OpenSpec', result.stderr)
        self.assertEqual(glossary.read_bytes(), before)

    def test_invalid_config_fails_without_fallback(self):
        for config in ['{', '[]', '{"unknown": "value"}', '{"corpus_root": 1}', '{"openspec_root": ""}']:
            with self.subTest(config=config):
                self.write('wiki.config.json', config)
                self.assertEqual(self.run_cli('status').returncode, 2)

    def test_rejects_absolute_and_escaping_profile_paths(self):
        for key in ('corpus_root', 'openspec_root'):
            for value in (str(self.root), '../outside', 'C:\\outside'):
                with self.subTest(key=key, value=value):
                    self.profile(**{key: value})
                    self.assertEqual(self.run_cli('lint', '--fix').returncode, 2)

    def test_rejects_external_symlink_root_and_profile(self):
        outside = self.root.parent / 'outside'
        outside.mkdir()
        (self.root / 'external').symlink_to(outside, target_is_directory=True)
        self.profile(corpus_root='external')
        self.assertEqual(self.run_cli('status').returncode, 2)
        (self.root / 'wiki.config.json').unlink()
        target = outside / 'config.json'
        target.write_text('{}')
        (self.root / 'wiki.config.json').symlink_to(target)
        self.assertEqual(self.run_cli('status').returncode, 2)

    def test_fix_relocated_glossary_is_idempotent(self):
        self.relocate()
        path = self.write('docs/wiki/knowledge/GLOSSARY.md', '# Glossary\n\n## Z\n\nZ.\n\n## A\n\nA.\n')
        self.assertEqual(self.run_cli('lint', '--fix').returncode, 0)
        self.assertLess(path.read_text().index('## A'), path.read_text().index('## Z'))
        before = path.stat().st_mtime_ns
        self.assertEqual(self.run_cli('lint', '--fix').returncode, 0)
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_fix_refuses_symlink_in_relocated_corpus_ancestry(self):
        self.relocate()
        (self.root / 'docs').rename(self.root / 'actual-docs')
        (self.root / 'docs').symlink_to(self.root / 'actual-docs', target_is_directory=True)
        path = self.write('docs/wiki/knowledge/GLOSSARY.md', '# Glossary\n\n## Z\n\nZ.\n\n## A\n\nA.\n')
        before = path.read_bytes()
        self.assertEqual(self.run_cli('lint', '--fix').returncode, 2)
        self.assertEqual(path.read_bytes(), before)

    def test_status_discovers_unconfigured_view_without_empty_directories(self):
        self.write('knowledge/operations/page.md', '# Operation\n')
        result = self.run_cli('status')
        self.assertEqual(result.returncode, 0)
        self.assertIn('Представление operations: 1', result.stdout)
        self.assertNotIn('Представление discovery:', result.stdout)

    def test_rejects_overlapping_openspec_and_corpus_layers(self):
        for value in ('.', 'knowledge', 'knowledge/specs'):
            with self.subTest(value=value):
                (self.root / value).mkdir(parents=True, exist_ok=True)
                self.profile(openspec_root=value)
                self.assertEqual(self.run_cli('status').returncode, 2)

    def test_copied_cli_runs_without_original_project_corpus(self):
        import subprocess
        import sys
        from tests.wiki_harness.test_cli import BIN_DIR
        copied = self.root / 'bin/wiki'
        shutil.copytree(BIN_DIR, copied, ignore=shutil.ignore_patterns('__pycache__'))
        self.relocate()
        self.write('docs/wiki/raw/source.md', '# Source\n')
        for command, args in [('lint', ('--dry-run',)), ('status', ()), ('find-orphans', ()), ('affected', ('source',))]:
            with self.subTest(command=command):
                result = subprocess.run([sys.executable, str(copied / command), *args],
                    cwd=self.root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_nested_checkout_does_not_fall_back_to_parent_corpus(self):
        import subprocess
        import sys
        from tests.wiki_harness.test_cli import BIN_DIR
        nested = self.root / 'nested'
        (nested / '.git').mkdir(parents=True)
        result = subprocess.run([sys.executable, str(BIN_DIR / 'status')],
            cwd=nested, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)


    def test_default_profile_does_not_require_openspec(self):
        shutil.rmtree(self.root / 'openspec')
        for command, args in [('lint', ('--dry-run',)), ('status', ()), ('find-orphans', ()), ('affected', ('Glossary',))]:
            with self.subTest(command=command):
                result = self.run_cli(command, *args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / 'openspec').exists())

    def test_null_openspec_and_independent_paths(self):
        shutil.rmtree(self.root / 'openspec')
        (self.root / 'docs').mkdir()
        (self.root / 'raw').rename(self.root / 'docs/evidence')
        (self.root / 'knowledge').rename(self.root / 'docs/wiki')
        (self.root / 'docs/wiki/GLOSSARY.md').rename(self.root / 'docs/wiki/terms.md')
        self.write('docs/wiki/navigation.md', '[Topic](topics/topic/page.md)\n')
        self.write('docs/wiki/topics/topic/page.md', '[Source](../../../evidence/source.md)\n')
        self.write('docs/evidence/source.md', '# Source\n')
        self.profile(raw_root='docs/evidence', knowledge_root='docs/wiki', openspec_root=None,
            documents={'glossary': 'terms.md', 'index': 'navigation.md'}, layers={'domains': 'topics'})
        result = self.run_cli('lint', '--dry-run')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('W_INDEX_MISSING', result.stdout)
        result = self.run_cli('affected', 'docs/evidence/source.md')
        self.assertIn('docs/wiki/topics/topic/page.md', result.stdout)
        self.assertIn('Доменные страницы: 1', self.run_cli('status').stdout)

    def test_custom_decision_names_and_disabled_glossary(self):
        self.profile(decision_name_pattern=r'^ADR-[0-9]+[.]md$', documents={'glossary': None})
        (self.root / 'knowledge/GLOSSARY.md').unlink()
        self.write('knowledge/decisions/ADR-001.md', '# Choice\n')
        result = self.run_cli('lint', '--dry-run')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.write('knowledge/decisions/bad.md', '# Bad\n')
        self.assertIn('E_DECISION_NAME', self.run_cli('lint').stdout)

    def test_profile_rejects_bad_nested_paths_before_any_fix(self):
        glossary = self.write('knowledge/GLOSSARY.md', '# Terms\n\n## Z\n\nZ.\n\n## A\n\nA.\n')
        before = glossary.read_bytes()
        for values in ({'documents': {'glossary': '../outside.md'}},
                       {'layers': {'domains': '/outside'}},
                       {'layers': {'unknown': 'topic'}},
                       {'knowledge_root': 'raw'},
                       {'raw_root': 'knowledge/sources'},
                       {'decision_name_pattern': '['},
                       {'glossary_sort': 'unsupported'}):
            with self.subTest(values=values):
                self.profile(**values)
                self.assertEqual(self.run_cli('lint', '--fix').returncode, 2)
                self.assertEqual(glossary.read_bytes(), before)

    def test_unicode_glossary_order_supports_other_writing_systems(self):
        self.profile(glossary_sort='unicode', language='el', project_name='Lab')
        path = self.write('knowledge/GLOSSARY.md', '# Terms\n\n## А\n\nCyrillic.\n\n## Ω\n\nGreek.\n\n## A\n\nLatin.\n')
        result = self.run_cli('lint', '--fix')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        actual = [line[3:] for line in path.read_text().splitlines() if line.startswith('## ')]
        self.assertEqual(actual, ['A', 'Ω', 'А'])
        before = path.read_bytes()
        self.assertEqual(self.run_cli('lint', '--fix').returncode, 0)
        self.assertEqual(path.read_bytes(), before)
