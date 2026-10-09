import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from tests.wiki_harness.test_cli import BIN_DIR, WikiCliTestCase


class DoctorTest(WikiCliTestCase):
    def setUp(self):
        super().setUp()
        self.home = self.root.parent / "home"
        self.home.mkdir()
        self.tools = self.root.parent / "tools"
        self.tools.mkdir()
        self.env = {**os.environ, "HOME": str(self.home),
                    "CODEX_HOME": str(self.home / ".codex"),
                    "XDG_CONFIG_HOME": str(self.home / ".config"),
                    "PATH": str(self.tools)}
        self.write("knowledge/SCHEMA.md", "# Schema\n")
        self.write("knowledge/index.md", "# Index\n")

    def doctor(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(BIN_DIR / "doctor"), *args],
                              cwd=cwd or self.root, env=self.env,
                              capture_output=True, text=True)

    def report(self, *args, code=0, cwd=None):
        run = self.doctor(*args, "--json", cwd=cwd)
        self.assertEqual(run.returncode, code, run.stdout + run.stderr)
        report = json.loads(run.stdout)
        self.assertEqual(report["exit_code"], code)
        return {check["id"]: check for check in report["checks"]}

    def profile(self, **values):
        self.write("wiki.config.json", json.dumps(values))

    def cli(self, body="print('1.14.1')"):
        path = self.tools / "openspec"
        path.write_text(f"#!{sys.executable}\n{body}\n")
        path.chmod(0o755)
        return path

    def skill(self, directory, name="openspec-explore", text=None):
        path = Path(directory) / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text or f"---\nname: {name}\ndescription: Explore a change\n---\n\n# Explore\n")
        return path

    def ready(self):
        self.profile(openspec_root="openspec")
        self.cli()
        self.skill(self.root / ".agents/skills")
        self.skill(self.root / ".claude/skills")

    def test_optional_missing_openspec_does_not_block_wiki(self):
        checks = self.report()
        self.assertEqual(checks["openspec.cli"]["status"], "warning")
        self.assertEqual(checks["openspec.skills.codex"]["status"], "warning")
        self.assertEqual(checks["openspec.root"]["status"], "skipped")
        self.assertEqual(checks["path.layers.views"]["status"], "skipped")

    def test_connected_openspec_requires_cli_and_selected_skills(self):
        self.profile(openspec_root="openspec")
        checks = self.report(code=1)
        self.assertEqual(checks["openspec.cli"]["status"], "error")
        self.assertEqual(checks["openspec.skills.claude"]["status"], "error")
        self.assertIn("remedy", checks["openspec.cli"])

    def test_strict_mode_requires_explicit_openspec_root(self):
        self.cli()
        self.skill(self.root / ".agents/skills")
        checks = self.report("--require-openspec", "--tools", "codex", code=1)
        self.assertEqual(checks["openspec.root"]["status"], "error")

    def test_three_tools_with_shared_opencode_skills(self):
        self.ready()
        checks = self.report("--require-openspec")
        for tool in ("codex", "claude", "opencode"):
            self.assertEqual(checks[f"openspec.skills.{tool}"]["status"], "ok")
        self.assertIn("1.14.1", checks["openspec.cli"]["message"])
        self.assertEqual(checks["openspec.cli"]["path"], str(self.tools / "openspec"))

    def test_tool_selection_and_native_opencode_path(self):
        self.profile(openspec_root="openspec")
        self.cli()
        self.skill(self.root / ".opencode/skills")
        checks = self.report("--tools", "opencode")
        self.assertNotIn("openspec.skills.codex", checks)
        self.assertEqual(checks["openspec.skills.opencode"]["status"], "ok")

    def test_legacy_codex_directory_is_reported(self):
        self.cli()
        self.skill(self.root / ".codex/skills")
        checks = self.report("--tools", "codex")
        self.assertEqual(checks["openspec.skills.codex"]["status"], "ok")
        self.assertTrue(any("legacy" in check["message"].lower() for check in checks.values()))

    def test_global_paths_honor_codex_home_and_xdg_config_home(self):
        self.profile(openspec_root="openspec")
        self.cli()
        codex = self.home / "custom-codex"
        xdg = self.home / "custom-config"
        self.env["CODEX_HOME"] = str(codex)
        self.env["XDG_CONFIG_HOME"] = str(xdg)
        self.skill(codex / "skills")
        self.skill(self.home / ".claude/skills")
        self.skill(xdg / "opencode/skills")
        checks = self.report()
        for tool in ("codex", "claude", "opencode"):
            self.assertEqual(checks[f"openspec.skills.{tool}"]["status"], "ok")
        self.assertIn(str(codex / "skills"), checks["openspec.skills.codex"]["searched"])

    def test_relative_internal_skill_alias_is_supported(self):
        self.ready()
        shutil.rmtree(self.root / ".claude/skills")
        (self.root / ".claude/skills").symlink_to("../.agents/skills", target_is_directory=True)
        self.assertEqual(self.report()["openspec.skills.claude"]["status"], "ok")

    def test_broken_skill_is_not_masked_by_another_valid_skill(self):
        self.ready()
        self.skill(self.root / ".agents/skills", "openspec-apply-change", "# no frontmatter\n")
        checks = self.report(code=1)
        self.assertTrue(any(check["status"] == "error" and "SKILL.md" in check.get("path", "")
                            for check in checks.values()))

    def test_broken_and_external_local_skill_aliases_are_errors(self):
        self.profile(openspec_root="openspec")
        self.cli()
        directory = self.root / ".agents/skills"
        directory.mkdir(parents=True)
        (directory / "openspec-explore").symlink_to("missing")
        checks = self.report("--tools", "codex", code=1)
        self.assertTrue(any("symlink" in check["message"] for check in checks.values()))
        (directory / "openspec-explore").unlink()
        external = self.skill(self.home / ".agents/skills").parent
        (directory / "openspec-explore").symlink_to(external, target_is_directory=True)
        checks = self.report("--tools", "codex", code=1)
        self.assertTrue(any("checkout" in check["message"] for check in checks.values()))

    def test_cli_failure_empty_version_and_timeout(self):
        self.profile(openspec_root="openspec")
        self.skill(self.root / ".agents/skills")
        for body in ("raise SystemExit(3)", "print('')", "import time; time.sleep(5)"):
            with self.subTest(body=body):
                self.cli(body)
                checks = self.report("--tools", "codex", "--timeout", "0.05", code=1)
                self.assertEqual(checks["openspec.cli"]["status"], "error")

    def test_invalid_profile_still_reports_environment(self):
        self.write("wiki.config.json", "{broken")
        self.cli()
        checks = self.report("--tools", "codex", code=2)
        self.assertEqual(checks["profile"]["status"], "error")
        self.assertEqual(checks["openspec.cli"]["status"], "ok")
        self.assertIn("wiki.config.json", checks["profile"]["path"])

    def test_unsafe_profile_paths_and_overlaps(self):
        for config in ({"raw_root": "../escape"}, {"raw_root": "knowledge"},
                       {"layers": {"views": "domains/nested"}},
                       {"documents": {"schema": "/tmp/schema.md"}}):
            with self.subTest(config=config):
                self.profile(**config)
                self.assertEqual(self.report(code=2)["profile"]["status"], "error")

    def test_required_files_types_and_lazy_layers(self):
        (self.root / "raw").rmdir()
        (self.root / "raw").write_text("not a directory")
        (self.root / "knowledge/SCHEMA.md").unlink()
        (self.root / "knowledge/domains").write_text("not a directory")
        checks = self.report(code=1)
        self.assertEqual(checks["path.raw_root"]["status"], "error")
        self.assertEqual(checks["path.documents.schema"]["status"], "error")
        self.assertEqual(checks["path.layers.domains"]["status"], "error")
        self.assertEqual(checks["path.layers.views"]["status"], "skipped")

    def test_relocated_profile_disabled_docs_and_nested_worktree_cwd(self):
        (self.root / ".git").rmdir()
        (self.root / ".git").write_text("gitdir: /unused\n")
        (self.root / "docs").mkdir()
        (self.root / "raw").rename(self.root / "docs/evidence")
        (self.root / "knowledge").rename(self.root / "docs/wiki")
        self.profile(raw_root="docs/evidence", knowledge_root="docs/wiki",
                     documents={"synthesis": None}, layers={"views": "perspectives"})
        checks = self.report(cwd=self.root / "docs/wiki")
        self.assertEqual(checks["path.documents.synthesis"]["status"], "skipped")
        self.assertTrue(checks["path.raw_root"]["path"].endswith("docs/evidence"))
        run = self.doctor("--project", str(self.root), "--json", cwd=self.home)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(json.loads(run.stdout)["project"], str(self.root.resolve()))

    def test_doctor_creates_no_files_or_bytecode_in_project(self):
        self.ready()
        before = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.root.rglob("*") if p.is_file()}
        self.report()
        after = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(any(BIN_DIR.glob("__pycache__/_doctor*.pyc")))

    def test_invalid_arguments_and_missing_project(self):
        for args in (("--tools", "other"), ("--tools", ""), ("--timeout", "0"),
                     ("--timeout", "nan"), ("--project", str(self.root / "missing"))):
            with self.subTest(args=args):
                self.assertEqual(self.doctor(*args).returncode, 2)

    def test_human_report_shows_remedies(self):
        run = self.doctor("--require-openspec")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("OpenSpec", run.stdout)
        self.assertIn("openspec init", run.stdout)

    def test_skill_name_description_and_body_must_be_usable(self):
        self.profile(openspec_root="openspec")
        self.cli()
        for text in ("---\nname: wrong\ndescription: Good\n---\nBody\n",
                     "---\nname: openspec-explore\n---\nBody\n",
                     "---\nname: openspec-explore\ndescription: Good\n---\n",
                     "---\nname: openspec-explore\ndescription: Good\n"):
            with self.subTest(text=text):
                self.skill(self.root / ".agents/skills", text=text)
                self.assertEqual(self.report("--tools", "codex", code=1)
                                 ["openspec.skills.codex"]["status"], "error")

    def test_block_description_is_supported(self):
        self.cli()
        self.skill(self.root / ".agents/skills", text="---\nname: openspec-explore\ndescription: >-\n  Explore a change\n  in the project\n---\nBody\n")
        self.assertEqual(self.report("--tools", "codex")["openspec.skills.codex"]["status"], "ok")

    def test_missing_connected_openspec_directory_is_profile_error(self):
        self.profile(openspec_root="planning/specs")
        checks = self.report(code=2)
        self.assertIn("planning/specs", checks["profile"]["message"])
        self.assertIn("openspec.cli", checks)

    def test_symlink_profile_escape_is_reported_without_reading_external_config(self):
        outside = self.root.parent / "config.json"
        outside.write_text("{broken")
        (self.root / "wiki.config.json").symlink_to(outside)
        self.assertIn("repository", self.report(code=2)["profile"]["message"])

    def test_cli_exists_but_is_not_executable(self):
        self.profile(openspec_root="openspec")
        self.skill(self.root / ".agents/skills")
        path = self.cli()
        path.chmod(0o644)
        self.assertEqual(self.report("--tools", "codex", code=1)["openspec.cli"]["status"], "error")

    def test_broken_profile_symlink_never_falls_back_to_defaults(self):
        (self.root / "wiki.config.json").symlink_to("missing-config.json")
        checks = self.report(code=2)
        self.assertEqual(checks["profile"]["status"], "error")
        self.assertIn("symlink", checks["profile"]["message"])

    def test_unreadable_skill_root_is_not_masked_by_valid_root(self):
        self.profile(openspec_root="openspec")
        self.cli()
        self.skill(self.root / ".agents/skills")
        unreadable = self.root / ".codex/skills"
        unreadable.mkdir(parents=True)
        unreadable.chmod(0o000)
        try:
            try:
                list(unreadable.iterdir())
            except PermissionError:
                pass
            else:
                self.skipTest("Process can read directories with mode 000")
            checks = self.report("--tools", "codex", code=1)
            self.assertEqual(checks["openspec.skills.codex"]["status"], "error")
        finally:
            unreadable.chmod(0o755)

    def test_non_string_description_is_not_a_loadable_skill(self):
        self.profile(openspec_root="openspec")
        self.cli()
        for value in ("false", "true", "123", "1.5", "[]", "{}", "null # missing", "# empty"):
            with self.subTest(value=value):
                self.skill(self.root / ".agents/skills", text=f"---\nname: openspec-explore\ndescription: {value}\n---\nBody\n")
                self.assertEqual(self.report("--tools", "codex", code=1)
                                 ["openspec.skills.codex"]["status"], "error")
        self.skill(self.root / ".agents/skills", text='---\nname: openspec-explore\ndescription: "123"\n---\nBody\n')
        self.assertEqual(self.report("--tools", "codex")["openspec.skills.codex"]["status"], "ok")
