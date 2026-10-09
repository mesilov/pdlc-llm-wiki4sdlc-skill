import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/install.py'
AGENTS = {'claude': 'Claude Code', 'codex': 'Codex', 'opencode': 'OpenCode'}


class TerminalInput(io.StringIO):
    def isatty(self):
        return True


class InstallAgentsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = self.root / 'project with spaces'
        self.target.mkdir()
        spec = importlib.util.spec_from_file_location('wiki_installer', SCRIPT)
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)

    def tearDown(self):
        self.temp.cleanup()

    def install(self, *args, target=None):
        return subprocess.run([sys.executable, str(SCRIPT), str(target or self.target), *args],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=10)

    def terminal_install(self, answers, *args):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', [str(SCRIPT), str(self.target), *args]), \
                patch.object(sys, 'stdin', TerminalInput(answers)), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = self.installer.main()
        return code, output.getvalue(), errors.getvalue()

    def assert_complete_kit(self, target, agent):
        canonical = target / '.agents/skills'
        self.assertEqual(len(list(canonical.glob('wiki-*/SKILL.md'))), 8)
        for name in self.installer.SKILLS:
            source = ROOT / 'skills' / name
            for path in self.installer.source_files(source, ROOT):
                self.assertEqual((canonical / name / path.relative_to(source)).read_bytes(),
                                 path.read_bytes())
            if agent == 'claude':
                alias = target / '.claude/skills' / name
                self.assertTrue(alias.is_symlink())
                self.assertFalse(os.path.isabs(os.readlink(alias)))
                self.assertEqual(alias.resolve(), (canonical / name).resolve())
        if agent != 'claude':
            self.assertFalse((target / '.claude').exists())
        self.assertFalse((canonical / 'pdlc-wiki-maintainer').exists())
        self.assertFalse((target / 'AGENTS.md').exists())

    def test_explicit_agents_install_complete_kit_and_cli(self):
        for agent, label in AGENTS.items():
            with self.subTest(agent=agent):
                target = self.root / agent
                target.mkdir()
                result = self.install('--agent', agent, '--init-wiki', target=target)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'Агент: {label}', result.stdout)
                self.assertIn(str(target), result.stdout)
                self.assert_complete_kit(target, agent)
                run = subprocess.run([sys.executable, str(target / 'bin/wiki/lint'), '--dry-run'],
                                     cwd=target, capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_each_agent_dry_run_reports_paths_without_writes(self):
        for agent, label in AGENTS.items():
            with self.subTest(agent=agent):
                result = self.install('--agent', agent, '--init-wiki', '--dry-run')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'Агент: {label}', result.stdout)
                self.assertIn('.agents/skills', result.stdout)
                self.assertIn('bin/wiki', result.stdout)
                if agent == 'claude':
                    self.assertIn('.claude/skills', result.stdout)
                self.assertEqual(list(self.target.iterdir()), [])

    def test_repeat_each_agent_preserves_contents_and_mtimes(self):
        for agent in AGENTS:
            with self.subTest(agent=agent):
                target = self.root / agent
                target.mkdir()
                self.assertEqual(self.install('--agent', agent, '--init-wiki', target=target).returncode, 0)
                before = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                          for p in target.rglob('*') if p.is_file()}
                result = self.install('--agent', agent, '--init-wiki', target=target)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Файлов: 0; ссылок: 0', result.stdout)
                self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns)
                                          for p in target.rglob('*') if p.is_file()})

    def test_conflict_for_each_agent_is_rejected_before_writes(self):
        for agent in AGENTS:
            with self.subTest(agent=agent):
                target = self.root / agent
                entry = target / 'bin/wiki/lint'
                entry.parent.mkdir(parents=True)
                entry.write_text('local edit\n')
                result = self.install('--agent', agent, '--init-wiki', target=target)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('Конфликт', result.stderr)
                self.assertEqual(entry.read_text(), 'local edit\n')
                self.assertFalse((target / '.agents').exists())
                self.assertFalse((target / 'knowledge').exists())

    def test_claude_alias_conflict_is_rejected_before_canonical_copy(self):
        alias = self.target / '.claude/skills/wiki-query'
        alias.mkdir(parents=True)
        result = self.install('--agent', 'claude', '--init-wiki')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('Конфликт', result.stderr)
        self.assertFalse((self.target / '.agents').exists())
        self.assertFalse((self.target / 'knowledge').exists())

    def test_legacy_claude_skips_menu_and_combines_with_explicit_claude(self):
        code, output, errors = self.terminal_install('', '--claude', '--dry-run')
        self.assertEqual(code, 0, errors)
        self.assertIn('Агент: Claude Code', output)
        self.assertNotIn('Для какого агента', output)
        result = self.install('--agent', 'claude', '--claude')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_complete_kit(self.target, 'claude')

    def test_conflicting_claude_flag_and_invalid_agent_leave_no_files(self):
        for args in [('--claude', '--agent', 'codex'),
                     ('--claude', '--agent', 'opencode'), ('--agent', 'unknown')]:
            with self.subTest(args=args):
                result = self.install(*args, '--init-wiki')
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(list(self.target.iterdir()), [])

    def test_non_terminal_default_remains_codex_without_reading_stdin(self):
        result = self.install('--init-wiki')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Агент: Codex', result.stdout)
        self.assertNotIn('Для какого агента', result.stdout)
        self.assert_complete_kit(self.target, 'codex')

    def test_terminal_menu_accepts_all_numbers_and_names(self):
        for answer, agent in [('1', 'claude'), ('2', 'codex'), ('3', 'opencode'),
                              ('claude', 'claude'), ('codex', 'codex'), ('opencode', 'opencode')]:
            with self.subTest(answer=answer):
                code, output, errors = self.terminal_install(answer + '\n', '--dry-run')
                self.assertEqual(code, 0, errors)
                for label in AGENTS.values():
                    self.assertIn(label, output)
                self.assertIn(f'Агент: {AGENTS[agent]}', output)
                self.assertEqual(list(self.target.iterdir()), [])

    def test_invalid_menu_input_retries_then_installs_chosen_agent(self):
        code, output, errors = self.terminal_install('wrong\n\n3\n', '--init-wiki')
        self.assertEqual(code, 0, errors)
        self.assertIn('Некорректный выбор', output)
        self.assertIn('Агент: OpenCode', output)
        self.assert_complete_kit(self.target, 'opencode')

    def test_explicit_agent_skips_menu_even_in_terminal(self):
        code, output, errors = self.terminal_install('', '--agent', 'claude', '--dry-run')
        self.assertEqual(code, 0, errors)
        self.assertNotIn('Для какого агента', output)
        self.assertIn('Агент: Claude Code', output)

    def test_menu_quit_and_eof_do_not_write(self):
        for answer, expected in [('q\n', 0), ('', 2)]:
            with self.subTest(answer=answer):
                code, output, errors = self.terminal_install(answer, '--init-wiki')
                self.assertEqual(code, expected, output + errors)
                self.assertEqual(list(self.target.iterdir()), [])

    def test_menu_keyboard_interrupt_does_not_write(self):
        with patch('builtins.input', side_effect=KeyboardInterrupt):
            code, output, errors = self.terminal_install('', '--init-wiki')
        self.assertEqual(code, 130, output + errors)
        self.assertEqual(list(self.target.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
