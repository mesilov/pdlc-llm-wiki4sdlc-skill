import json

from tests.wiki_harness.test_cli import WikiCliTestCase


class TraceTest(WikiCliTestCase):
    def setUp(self):
        super().setUp()
        self.write('wiki.config.json', json.dumps({'openspec_root': 'openspec'}))
        self.wiki = self.write('knowledge/domains/demo/requirements.md', '''# Требования
### Requirement: [WK-R1] Доступ
#### Scenario: [WK-S1] Новый пользователь
Given приглашение
When принятие
Then доступ
#### Scenario: [WK-S2] Существующий пользователь
Given аккаунт
When принятие
Then доступ
### Requirement: [WK-R2] Срок
#### Scenario: [WK-S3] Просрочено
Given истёкший срок
When принятие
Then отказ
''')
        self.spec = self.write('openspec/changes/add-demo/specs/demo/spec.md', '''# Demo
## ADDED Requirements
### Requirement: [OS-R1] Доступ
The system SHALL grant access.
#### Scenario: [OS-S1] Новый пользователь
- **GIVEN** приглашение
- **WHEN** принятие
- **THEN** доступ
#### Scenario: [OS-S2] Существующий пользователь
- **GIVEN** аккаунт
- **WHEN** принятие
- **THEN** доступ
### Requirement: [OS-R2] Срок
The system SHALL reject expired invitations.
#### Scenario: [OS-S3] Просрочено
- **GIVEN** истёкший срок
- **WHEN** принятие
- **THEN** отказ
''')
        self.decision = self.write('knowledge/decisions/2026-10-demo.md', '# Решение\nСтатус: proposed\n')
        self.write('knowledge/index.md', '# Индекс\n[Требования](domains/demo/requirements.md)\n')
        self.mapping = {
            'version': 1, 'feature': 'demo',
            'wiki_files': ['domains/demo/requirements.md'],
            'specs': [{'capability': 'demo', 'path': 'changes/add-demo/specs/demo/spec.md'}],
            'decisions': ['decisions/2026-10-demo.md'],
            'links': [
                {'requirement': f'OS-R{r}', 'scenario': f'OS-S{s}',
                 'wiki_requirements': [f'WK-R{r}'], 'wiki_scenarios': [f'WK-S{s}']}
                for r, s in ((1, 1), (1, 2), (2, 3))],
            'review': {'status': 'pending'},
        }
        self.save_map()

    def save_map(self):
        self.map_path = self.write('knowledge/domains/demo/traceability.json', json.dumps(self.mapping))

    def report(self, *args, expected=0):
        result = self.run_cli('trace', '--json', *args)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def codes(self, report):
        return {issue['code'] for issue in report['issues']}

    def test_complete_graph_has_pending_review_and_reverse_links(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report = self.report('demo')
        feature = report['features'][0]
        self.assertEqual(feature['coverage']['openspec_scenarios'], {'total': 3, 'linked': 3})
        self.assertEqual(feature['coverage']['wiki_scenarios']['covered'], 3)
        self.assertEqual(feature['semantic_review'], 'pending')
        self.assertFalse(feature['ready'])
        self.assertEqual(feature['reverse']['WK-S1'], ['OS-S1'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_optional_openspec_and_empty_scope(self):
        self.write('wiki.config.json', '{}')
        self.assertEqual(self.run_cli('trace').returncode, 2)
        self.assertNotIn('E_TRACE', self.run_cli('lint').stdout)
        self.write('wiki.config.json', json.dumps({'openspec_root': 'openspec'}))
        self.map_path.unlink()
        self.assertEqual(self.report()['checked_maps'], 0)
        self.report('--require-reviewed', expected=1)
        self.assertEqual(self.run_cli('trace', 'missing').returncode, 2)

    def test_empty_spec_cannot_be_ready_even_when_wiki_is_excluded(self):
        self.spec.write_text('# Пустая спецификация\n')
        self.mapping['links'] = []
        self.mapping['exclusions'] = [{'id': identifier, 'reason': 'Вне scope'}
                                      for identifier in ('WK-R1', 'WK-R2', 'WK-S1', 'WK-S2', 'WK-S3')]
        self.save_map()
        report = self.report(expected=1)
        self.assertIn('E_TRACE_SCOPE_EMPTY', self.codes(report))
        self.mapping['review'] = {'status': 'reviewed', 'reviewer': 'tester', 'note': 'Проверено',
                                  'fingerprint': report['features'][0]['fingerprint']}
        self.save_map()
        self.assertFalse(self.report('--require-reviewed', expected=1)['features'][0]['ready'])

    def test_new_spec_scenario_breaks_coverage_and_lint(self):
        self.spec.write_text(self.spec.read_text() + '\n#### Scenario: [OS-S4] Другой\n')
        self.assertIn('E_TRACE_SCENARIO_UNLINKED', self.codes(self.report(expected=1)))
        lint = self.run_cli('lint')
        self.assertEqual(lint.returncode, 1)
        self.assertIn('E_TRACE_SCENARIO_UNLINKED', lint.stdout)

    def test_wiki_gap_and_explicit_exclusion(self):
        self.wiki.write_text(self.wiki.read_text() + '\n#### Scenario: [WK-S4] Позже\n')
        self.assertIn('E_TRACE_WIKI_UNCOVERED', self.codes(self.report(expected=1)))
        self.mapping['exclusions'] = [{'id': 'WK-S4', 'reason': 'Отложено выбранным scope'}]
        self.save_map()
        coverage = self.report()['features'][0]['coverage']['wiki_scenarios']
        self.assertEqual(coverage, {'total': 4, 'in_scope': 3, 'covered': 3, 'excluded': 1})
        self.mapping['exclusions'][0]['reason'] = ''
        self.save_map()
        self.assertIn('E_TRACE_SCHEMA', self.codes(self.report(expected=1)))

    def test_unknown_ids_wrong_parent_and_duplicate_links(self):
        for field, value, code in (
                ('requirement', 'OS-R2', 'E_TRACE_PARENT'),
                ('wiki_requirements', ['WK-R2'], 'E_TRACE_PARENT'),
                ('wiki_scenarios', ['WK-UNKNOWN'], 'E_TRACE_ID')):
            with self.subTest(field=field):
                original = self.mapping['links'][0][field]
                self.mapping['links'][0][field] = value
                self.save_map()
                self.assertIn(code, self.codes(self.report(expected=1)))
                self.mapping['links'][0][field] = original
        self.mapping['links'].append(self.mapping['links'][0])
        self.save_map()
        self.assertIn('E_TRACE_LINK_DUPLICATE', self.codes(self.report(expected=1)))

    def test_missing_duplicate_ids_and_fenced_examples(self):
        original = self.spec.read_text()
        self.spec.write_text(original + '\n```md\n#### Scenario: Example\n```\n')
        self.report()
        self.spec.write_text(original + '\n#### Scenario: Без ID\n')
        self.assertIn('E_TRACE_ID_MISSING', self.codes(self.report(expected=1)))
        self.spec.write_text(original + '\n#### Scenario: [OS-S1] Повтор\n')
        self.assertIn('E_TRACE_ID_DUPLICATE', self.codes(self.report(expected=1)))

    def test_wrong_heading_level_does_not_hide_scenarios_or_requirements(self):
        original = self.spec.read_text()
        for heading in ('##### Scenario: [OS-S4] Ещё', '### Scenario: [OS-S4] Ещё',
                        '## Requirement: [OS-R3] Ещё', '#### Requirement: [OS-R3] Ещё'):
            with self.subTest(heading=heading):
                self.spec.write_text(original + '\n' + heading + '\n')
                report = self.report(expected=1)
                self.assertIn('E_TRACE_HEADING', self.codes(report))
                self.mapping['review'] = {'status': 'reviewed', 'reviewer': 'tester', 'note': 'Проверено',
                                          'fingerprint': report['features'][0]['fingerprint']}
                self.save_map()
                self.assertFalse(self.report('--require-reviewed', expected=1)['features'][0]['ready'])

    def test_review_is_bound_to_files_and_map_definition(self):
        self.report('--require-reviewed', expected=1)
        fingerprint = self.report()['features'][0]['fingerprint']
        self.mapping['review'] = {'status': 'reviewed', 'reviewer': 'maintainer',
                                  'note': 'Проверены Given/When/Then и ограничения', 'fingerprint': fingerprint}
        self.save_map()
        self.assertTrue(self.report('--require-reviewed')['features'][0]['ready'])
        for path in (self.wiki, self.spec, self.decision):
            original = path.read_text()
            path.write_text(original + '\nУточнение.\n')
            feature = self.report('--require-reviewed', expected=1)['features'][0]
            self.assertEqual(feature['semantic_review'], 'stale')
            path.write_text(original)
        self.mapping['links'][0]['wiki_scenarios'].append('WK-S2')
        self.save_map()
        self.assertEqual(self.report()['features'][0]['semantic_review'], 'stale')

    def test_unsafe_missing_paths_and_malformed_maps(self):
        for path in ('../outside.md', '/tmp/outside.md', 'views/product/page.md'):
            with self.subTest(path=path):
                self.mapping['wiki_files'] = [path]
                self.save_map()
                self.assertIn('E_TRACE_SCHEMA', self.codes(self.report(expected=1)))
        self.map_path.write_text('{broken')
        self.assertIn('E_TRACE_SCHEMA', self.codes(self.report(expected=1)))

    def test_named_selection_reports_schema_errors_in_existing_map(self):
        del self.mapping['decisions']
        self.save_map()
        report = self.report('demo', expected=1)
        self.assertEqual(report['checked_maps'], 1)
        self.assertEqual(report['features'][0]['feature'], 'demo')
        self.assertIn('E_TRACE_SCHEMA', self.codes(report))

    def test_symlink_and_duplicate_feature_maps(self):
        outside = self.root.parent / 'outside.json'
        outside.write_text(json.dumps(self.mapping))
        self.map_path.unlink()
        self.map_path.symlink_to(outside)
        self.assertIn('E_TRACE_SCHEMA', self.codes(self.report(expected=1)))
        self.map_path.unlink()
        self.save_map()
        self.write('knowledge/domains/other/traceability.json', json.dumps(self.mapping))
        self.assertIn('E_TRACE_FEATURE_DUPLICATE', self.codes(self.report(expected=1)))

    def test_scope_follows_profile_and_requires_explicit_archive_update(self):
        (self.root / 'knowledge/domains').rename(self.root / 'knowledge/topics')
        self.mapping['wiki_files'] = ['topics/demo/requirements.md']
        self.map_path = self.write('knowledge/topics/demo/traceability.json', json.dumps(self.mapping))
        self.write('wiki.config.json', json.dumps({'openspec_root': 'openspec', 'layers': {'domains': 'topics'}}))
        self.report()
        self.spec.rename(self.spec.with_name('archived.md'))
        self.assertIn('E_TRACE_SCHEMA', self.codes(self.report(expected=1)))
