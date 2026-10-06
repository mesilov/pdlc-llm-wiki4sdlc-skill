"""Check the portable kit's entrypoints and cross-skill references."""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SkillPackageTest(unittest.TestCase):
    def test_only_eight_skill_manifests_are_bundled(self):
        manifests = set((ROOT / 'skills').rglob('SKILL.md'))
        self.assertEqual(manifests, set((ROOT / 'skills').glob('wiki-*/SKILL.md')))

    def test_utr_source_is_complete_and_matches_pinned_hashes(self):
        source = ROOT / 'skills/wiki-query/references/utr-source'
        manifest_path = source / 'manifest.json'
        self.assertTrue(manifest_path.is_file(), 'pinned UTR source manifest is missing')
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest['repository'], 'https://github.com/GregoryPletnev/SimpleEn-RU')
        self.assertEqual(manifest['commit'], 'aefcd51664f549801758bd5530d9e0f6bba415fc')
        self.assertEqual(manifest['local_paths'], {
            'skills/simple-russian/SKILL.md': 'skills/simple-russian/SKILL.source.md',
        })
        self.assertEqual(set(manifest['files']), {
            'skills/simple-russian/SKILL.md',
            'skills/simple-russian/references/checklist.md',
            'skills/simple-russian/references/use-cases.md',
            'examples/before-after-ru.md', 'examples/before-after.md',
            'evals/utr_lint.py', 'evals/md_blocks.py', 'LICENSE',
        })
        for name, digest in manifest['files'].items():
            with self.subTest(resource=name):
                path = source / manifest['local_paths'].get(name, name)
                self.assertTrue(path.is_file(), name)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_all_eight_entrypoints_have_valid_names_and_descriptions(self):
        folders = sorted((ROOT / 'skills').glob('wiki-*'))
        self.assertEqual(len(folders), 8)
        for folder in folders:
            with self.subTest(skill=folder.name):
                text = (folder / 'SKILL.md').read_text()
                match = re.match(r'^---\nname: ([a-z0-9-]+)\ndescription: ("[^\n]+")\n---\n', text)
                self.assertIsNotNone(match)
                self.assertEqual(match[1], folder.name)
                description = json.loads(match[2])
                self.assertLessEqual(len(description), 1024)
                self.assertTrue(description.startswith('Use when'))
                interface = (folder / 'agents/openai.yaml').read_text()
                self.assertIn('$' + folder.name, interface)

    def test_every_reference_in_skill_markdown_resolves_inside_kit(self):
        for path in (ROOT / 'skills').rglob('*.md'):
            for target in re.findall(r'\[[^\]]*\]\(([^)\n]+)\)', path.read_text()):
                with self.subTest(path=path, target=target):
                    self.assertNotIn('://', target, 'references should be bundled in the kit')
                    resolved = (path.parent / target.split('#')[0]).resolve()
                    self.assertTrue(resolved.is_relative_to(ROOT))
                    self.assertTrue(resolved.exists(), target)

    def test_runtime_resources_do_not_embed_source_project_policy_or_paths(self):
        for directory in ('skills', 'bin', 'scripts', 'templates'):
            for path in (ROOT / directory).rglob('*'):
                if path.suffix not in ('.md', '.py', '.json', '.yaml'):
                    continue
                with self.subTest(path=path):
                    text = path.read_text().casefold()
                    self.assertNotIn('/users/mesilov', text)
                    self.assertNotIn('origin/dev', text)
