import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


BIN = Path(__file__).resolve().parents[2] / 'bin/wiki/raw-lint'
HEADER = '''---
type: Source material
title: Reference snapshot
description: Captured documentation and its limitations.
sources:
  - id: upstream
    resource: https://example.org/reference
---
# Reference snapshot

Captured documentation, context and limitations.
'''


class RawLintTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        for directory in ('.git', 'raw', 'knowledge'):
            (self.root / directory).mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, contents=HEADER):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
        return target

    def unit(self, contents=HEADER, category='sources', name='2026-10-09-reference', raw='raw'):
        return self.write(f'{raw}/{category}/api/{name}/README.md', contents)

    def run_cli(self, *args, without_site=False, cwd=None):
        command = [sys.executable, *(['-S'] if without_site else []), str(BIN), *args]
        return subprocess.run(command, cwd=cwd or self.root,
                              capture_output=True, text=True,
                              env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})

    def report(self, *args, exit_code=0):
        run = self.run_cli(*args, '--json')
        self.assertEqual(run.returncode, exit_code, run.stdout + run.stderr)
        return json.loads(run.stdout)

    def codes(self, report):
        return {finding['code'] for finding in report['findings']}

    def test_valid_units_and_original_markdown_are_read_only(self):
        source = self.unit()
        self.write(source.parent.relative_to(self.root) / 'original.md', '# Unwrapped original\n')
        self.unit(HEADER.replace('Source material', 'Research study'), category='research')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report = self.report()
        self.assertEqual(len(report['checked']), 2)
        self.assertEqual(report['summary']['errors'], 0)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_missing_frontmatter_and_missing_type_are_okf_errors(self):
        for contents, code in [('# Original\n', 'E_OKF_FRONTMATTER'),
                               ('---\ntitle: x\n---\n# X\n', 'E_OKF_TYPE')]:
            with self.subTest(code=code):
                self.unit(contents)
                self.assertIn(code, self.codes(self.report(exit_code=1)))

    def test_malformed_and_duplicate_yaml_fail(self):
        for header in ('type: [', 'type: Source material\ntype: Research study',
                       'type: !!python/object/apply:os.system ["touch injected"]'):
            with self.subTest(header=header):
                self.unit('---\n' + header + '\n---\n# Document\n')
                self.assertIn('E_OKF_YAML', self.codes(self.report(exit_code=1)))
                self.assertFalse((self.root / 'injected').exists())

    def test_invalid_yaml_timestamp_is_a_document_error(self):
        self.unit(HEADER.replace('sources:', 'stale_after: 2026-02-30\nsources:'))
        self.assertIn('E_OKF_YAML', self.codes(self.report(exit_code=1)))

    def test_yaml_constructor_errors_do_not_abort_other_documents(self):
        for number, field in enumerate(('custom: !!timestamp garbage', 'custom: !!int ""',
                                        'verified: {by: process:test, at: 2026-99-09T09:00:00Z}')):
            self.unit(HEADER.replace('sources:', field + '\nsources:'),
                      name=f'2026-10-09-invalid-{number}')
        self.unit()
        report = self.report(exit_code=1)
        self.assertEqual(len(report['checked']), 4)
        self.assertEqual(report['summary']['errors'], 3)
        self.assertEqual(self.codes(report), {'E_OKF_YAML'})

    def test_real_yaml_block_flow_aliases_and_extensions_are_allowed(self):
        self.unit('''---
type: Source material
title: Reference
description: >-
  A multiline
  description.
sources: [{id: upstream, resource: "https://example.org/reference"}]
custom: &notes {one: two}
other: *notes
---
# Reference

Source context.
''')
        self.assertEqual(self.report()['summary']['errors'], 0)

    def test_duplicate_merge_keys_are_rejected_but_single_merge_is_valid(self):
        self.unit('''---
type: Custom concept
one: &one {answer: one}
two: &two {answer: two}
custom: {<<: *one, <<: *two}
---
''')
        self.assertIn('E_OKF_YAML', self.codes(self.report('--okf-only', exit_code=1)))
        self.unit('''---
type: Custom concept
one: &one {answer: one}
custom: {<<: *one, answer: explicit}
---
''')
        self.report('--okf-only')

    def test_okf_minimum_is_valid_without_local_raw_fields(self):
        self.unit('---\ntype: Custom concept\ncustom: true\n---\n')
        report = self.report('--okf-only')
        self.assertEqual(report['mode'], 'okf')
        self.assertEqual(report['summary']['errors'], 0)
        self.assertIn('E_RAW_FIELD', self.codes(self.report(exit_code=1)))

    def test_raw_fields_sources_and_body_are_required(self):
        for old, new in [('title: Reference snapshot', 'title: ""'),
                         ('description: Captured documentation and its limitations.', 'description: []'),
                         ('sources:\n  - id: upstream\n    resource: https://example.org/reference', 'sources: {}'),
                         ('# Reference snapshot\n\nCaptured documentation, context and limitations.\n', '')]:
            with self.subTest(old=old):
                self.unit(HEADER.replace(old, new))
                self.assertGreater(self.report(exit_code=1)['summary']['errors'], 0)

    def test_duplicate_source_ids_and_missing_resources_fail_raw_contract(self):
        self.unit(HEADER.replace('sources:\n  - id: upstream\n    resource: https://example.org/reference',
                                'sources:\n  - {id: same, resource: https://example.org/one}\n  - {id: same}'))
        codes = self.codes(self.report(exit_code=1))
        self.assertIn('E_RAW_SOURCE_ID', codes)
        self.assertIn('E_RAW_FIELD', codes)

    def test_optional_guidance_is_warning_in_okf_mode(self):
        self.unit(HEADER.replace('sources:', 'verified: {by: process:test, at: yesterday}\nsources:'))
        self.assertIn('E_RAW_TIMESTAMP', self.codes(self.report(exit_code=1)))
        report = self.report('--okf-only')
        self.assertGreater(report['summary']['warnings'], 0)
        self.assertEqual(report['summary']['errors'], 0)

    def test_verified_mapping_list_and_timezone_dates(self):
        for value in ('{by: process:test, at: 2026-10-09T09:00:00Z}',
                      '[{by: human:reviewer, at: "2026-10-09T15:00:00+06:00"}]'):
            with self.subTest(value=value):
                self.unit(HEADER.replace('sources:', f'verified: {value}\nsources:'))
                self.report()

    def test_naive_dates_and_invalid_optional_shapes_fail(self):
        for field in ('verified: {by: process:test, at: 2026-10-09T09:00:00}',
                      'generated: {at: 2026-10-09T09:00:00Z}',
                      'stale_after: 2026-10-09', 'verified: text', 'tags: text',
                      'status: accepted'):
            with self.subTest(field=field):
                self.unit(HEADER.replace('sources:', field + '\nsources:'))
                self.report(exit_code=1)

    def test_empty_sources_and_missing_verification_are_allowed(self):
        self.unit(HEADER.replace('sources:\n  - id: upstream\n    resource: https://example.org/reference', 'sources: []'))
        self.report()

    def test_missing_root_and_bad_date_are_local_tree_errors(self):
        self.write('raw/sources/api/2026-10-09-missing/data.json', '{}\n')
        self.unit(name='2026-02-30-reference')
        codes = self.codes(self.report(exit_code=1))
        self.assertIn('E_RAW_ROOT', codes)
        self.assertIn('E_RAW_TREE', codes)

    def test_custom_root_categories_empty_list_and_nested_cwd(self):
        source = self.unit(HEADER.replace('Source material', 'Interview'), category='interviews', raw='evidence')
        config = self.write('wiki.config.json', json.dumps({'raw_root': 'evidence', 'raw_categories': ['interviews']}))
        self.assertEqual(len(self.report()['checked']), 1)
        run = self.run_cli('--json', cwd=source.parent)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        config.write_text(json.dumps({'raw_root': 'evidence', 'raw_categories': []}))
        self.assertEqual(self.report()['checked'], [])
        self.assertEqual(len(self.report(str(source.relative_to(self.root)))['checked']), 1)

    def test_nested_raw_categories_are_profile_errors_before_unit_scan(self):
        self.unit(category='customer/interviews')
        for category in ('customer/interviews', '.'):
            with self.subTest(category=category):
                self.write('wiki.config.json', json.dumps({'raw_categories': [category]}))
                before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
                report = self.report(exit_code=2)
                self.assertIn('raw_categories', report['error'])
                self.assertEqual(report['checked'], [])
                self.assertEqual(report['findings'], [])
                self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_custom_single_component_categories_accept_nondefault_names(self):
        for category in ('customer.interviews', 'customer interviews', 'материалы'):
            with self.subTest(category=category):
                self.unit(HEADER.replace('Source material', 'Interview'), category=category)
                self.write('wiki.config.json', json.dumps({'raw_categories': [category]}))
                report = self.report()
                self.assertEqual(report['summary']['checked'], 1)
                self.assertIn('/' + category + '/', report['checked'][0])

    def test_explicit_units_limit_scope(self):
        good = self.unit()
        self.unit('# Bad\n', name='2026-10-09-invalid')
        self.assertEqual(len(self.report(str(good.parent.relative_to(self.root)))['checked']), 1)
        self.report(exit_code=1)

    def test_okf_only_directory_scope_allows_custom_names_with_dots(self):
        source = self.unit('---\ntype: Custom concept\n---\n',
                           category='custom', name='reference-v0.2')
        self.assertEqual(len(self.report(str(source.parent.relative_to(self.root)), '--okf-only')['checked']), 1)
        self.assertEqual(len(self.report(str(source.relative_to(self.root)), '--okf-only')['checked']), 1)

    def test_source_paths_are_checked_locally_without_network(self):
        source = self.unit(HEADER.replace('https://example.org/reference', './snapshot.json'))
        self.assertIn('E_RAW_RESOURCE', self.codes(self.report(exit_code=1)))
        self.write(source.parent.relative_to(self.root) / 'snapshot.json', '{}\n')
        self.report()
        self.unit(HEADER.replace('https://example.org/reference', '../../../../../../outside.json'))
        self.assertIn('E_RAW_RESOURCE', self.codes(self.report(exit_code=1)))
        self.report('--okf-only')

    def test_source_paths_with_spaces_cannot_skip_containment(self):
        source = self.unit(HEADER.replace('https://example.org/reference', 'folder name/../../../../../../outside.json'))
        self.assertIn('E_RAW_RESOURCE', self.codes(self.report(exit_code=1)))
        source.write_text(HEADER.replace('https://example.org/reference', 'snapshot name.json'))
        self.write(source.parent.relative_to(self.root) / 'snapshot name.json', '{}\n')
        self.assertEqual(self.report()['summary']['warnings'], 0)
        source.write_text(HEADER.replace('https://example.org/reference', 'all queries in project X'))
        self.assertIn('W_RAW_SOURCE_SCOPE', self.codes(self.report()))

    def test_symlink_escape_is_reported_without_reading_target(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        payload = outside / 'README.md'
        payload.write_text(HEADER)
        unit = self.root / 'raw/sources/api/2026-10-09-linked'
        unit.parent.mkdir(parents=True)
        unit.symlink_to(outside, target_is_directory=True)
        self.assertIn('E_RAW_ESCAPE', self.codes(self.report(exit_code=1)))

    def test_explicit_outside_path_is_invalid_invocation(self):
        outside = Path(self.temp.name) / 'outside.md'
        outside.write_text(HEADER)
        self.report(str(outside), exit_code=2)

    def test_legacy_categories_are_preserved_and_reported(self):
        legacy = self.write('raw/observations/old.md', '# Original observation\n')
        report = self.report()
        self.assertEqual(report['checked'], [])
        self.assertIn('W_RAW_UNSCANNED', self.codes(report))
        self.assertEqual(legacy.read_text(), '# Original observation\n')

    def test_json_is_deterministic(self):
        self.unit('# Missing header\n', name='2026-10-09-z')
        self.unit(HEADER.replace('title: Reference snapshot', 'title: ""'), name='2026-10-09-a')
        first = self.run_cli('--json')
        second = self.run_cli('--json')
        self.assertEqual(first.returncode, 1)
        self.assertEqual(first.stdout, second.stdout)

    def test_missing_parser_is_actionable_tool_error(self):
        self.unit()
        run = self.run_cli('--json', without_site=True)
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn('PyYAML', run.stdout + run.stderr)
        self.assertNotIn('Traceback', run.stdout + run.stderr)

    def test_bad_profile_returns_json_error(self):
        self.write('wiki.config.json', '{')
        self.report(exit_code=2)

    def test_non_utf8_file_reports_a_finding(self):
        source = self.unit()
        source.write_bytes(b'\xff\xfe')
        self.assertIn('E_RAW_READ', self.codes(self.report(exit_code=1)))
