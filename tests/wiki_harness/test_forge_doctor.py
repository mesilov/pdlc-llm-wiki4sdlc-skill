"""Forge checks exercise the installed CLI boundary with read-only client fixtures."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from tests.wiki_harness.test_cli import BIN_DIR, WikiCliTestCase


GIT = shutil.which("git")


class ForgeDoctorTest(WikiCliTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.root.resolve()
        shutil.rmtree(self.root / ".git")
        self.home = self.root.parent / "home"
        self.home.mkdir()
        self.tools = self.root.parent / "tools"
        self.tools.mkdir()
        self.log = self.root.parent / "client-calls.jsonl"
        self.env = {**os.environ, "HOME": str(self.home),
                    "CODEX_HOME": str(self.home / ".codex"),
                    "XDG_CONFIG_HOME": str(self.home / ".config"),
                    "PATH": str(self.tools), "GIT_CONFIG_NOSYSTEM": "1"}
        (self.tools / "git").symlink_to(GIT)
        self.git("init", "-q")
        self.write("knowledge/SCHEMA.md", "# Schema\n")
        self.write("knowledge/index.md", "# Index\n")

    def git(self, *args, root=None):
        result = subprocess.run([GIT, *args], cwd=root or self.root, env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def remote(self, url="git@github.com:team/demo.git", name="origin"):
        self.git("remote", "add", name, url)

    def client(self, name="gh", responses=None, version=None):
        if responses is None:
            if name == "gh":
                responses = {
                    "/user": {"login": "reader", "id": 1, "html_url": "https://github.com/reader"},
                    "repos/team/demo": {"full_name": "team/demo", "html_url": "https://github.com/team/demo",
                                        "has_issues": True, "permissions": {"pull": True, "push": False}},
                    "repos/team/demo/issues?per_page=1": [],
                    "repos/team/demo/pulls?per_page=1": [],
                }
            else:
                responses = {
                    "/user": {"username": "reader", "id": 1, "web_url": "https://gitlab.com/reader"},
                    "projects/group%2Fsub%2Fdemo": {"path_with_namespace": "group/sub/demo",
                        "web_url": "https://gitlab.com/group/sub/demo", "issues_enabled": True,
                        "merge_requests_enabled": True, "permissions": {"project_access": {"access_level": 30}}},
                    "projects/group%2Fsub%2Fdemo/issues?per_page=1": [],
                    "projects/group%2Fsub%2Fdemo/merge_requests?per_page=1": [],
                }
        path = self.tools / name
        version = version or ("gh version 2.80.0 (2026-01-01)" if name == "gh" else "glab version 1.70.0 (2026-01-01)")
        code = f'''#!{sys.executable}
import json, os, sys, time
with open({str(self.log)!r}, "a") as stream:
    stream.write(json.dumps({{"argv": sys.argv, "cwd": os.getcwd(), "env": {{k: v for k, v in os.environ.items() if k.startswith(("GH_", "GLAB_", "GIT_", "GITLAB_")) or k in ("DEBUG", "PAGER", "NO_COLOR", "CI", "API_PROTOCOL")}}}}) + "\\n")
responses = {responses!r}
if sys.argv[1:] == ["--version"]:
    print({version!r})
    sys.exit(0)
if "--hostname" not in sys.argv or "--method" not in sys.argv or sys.argv[sys.argv.index("--method") + 1] != "GET":
    print("fixture requires explicit host and GET", file=sys.stderr)
    sys.exit(9)
value = responses.get(sys.argv[-1], {{"_returncode": 8, "_stderr": "unexpected endpoint"}})
if isinstance(value, dict) and any(key.startswith("_") for key in value):
    time.sleep(value.get("_sleep", 0))
    print(value.get("_stdout", ""))
    print(value.get("_stderr", ""), file=sys.stderr)
    sys.exit(value.get("_returncode", 0))
print(json.dumps(value))
'''
        path.write_text(code)
        path.chmod(0o755)
        return responses

    def doctor(self, *args, cwd=None, json_output=True):
        return subprocess.run([sys.executable, str(BIN_DIR / "doctor"), *args,
                               *(["--json"] if json_output else [])],
                              cwd=cwd or self.root, env=self.env, capture_output=True, text=True)

    def report(self, *args, code=0, cwd=None):
        result = self.doctor(*args, cwd=cwd)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["exit_code"], code)
        return {value["id"]: value for value in report["checks"]}

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_default_is_local_only_and_reports_selected_target_and_version(self):
        self.remote()
        self.client()
        checks = self.report()
        self.assertEqual(checks["forge.target"]["status"], "ok")
        self.assertEqual(checks["forge.target"]["host"], "github.com")
        self.assertEqual(checks["forge.target"]["repository"], "team/demo")
        self.assertEqual(checks["forge.target"]["remote"], "origin")
        self.assertEqual(checks["forge.cli"]["version"], "2.80.0")
        for name in ("auth", "repository", "issues", "pull_requests", "permissions", "write"):
            self.assertEqual(checks["forge." + name]["status"], "skipped")
        self.assertEqual([call["argv"][1:] for call in self.calls()], [["--version"]])

    def test_github_strict_reads_all_endpoints_and_keeps_write_unverified(self):
        self.remote("https://github.com/team/demo.git")
        self.client()
        checks = self.report("--require-forge")
        for name in ("target", "cli", "auth", "repository", "issues", "pull_requests", "permissions"):
            self.assertEqual(checks["forge." + name]["status"], "ok", name)
        self.assertEqual(checks["forge.permissions"]["permissions"], {"pull": True, "push": False})
        self.assertEqual(checks["forge.write"]["status"], "skipped")
        self.assert_read_only_calls("github.com")

    def assert_read_only_calls(self, host):
        for call in self.calls():
            argv = call["argv"]
            self.assertTrue(Path(argv[0]).is_absolute())
            self.assertEqual(call["cwd"], str(self.root))
            if argv[1:] != ["--version"]:
                self.assertEqual(argv[1], "api")
                self.assertEqual(argv[argv.index("--hostname") + 1], host)
                self.assertEqual(argv[argv.index("--method") + 1], "GET")
            self.assertNotIn("login", argv)
            self.assertNotIn("init", argv)

    def test_gitlab_nested_path_and_permissions_are_api_claims(self):
        self.remote("ssh://git@gitlab.com/group/sub/demo.git")
        self.client("glab")
        checks = self.report("--forge-network")
        self.assertEqual(checks["forge.repository"]["status"], "ok")
        self.assertEqual(checks["forge.issues"]["status"], "ok")
        self.assertEqual(checks["forge.pull_requests"]["status"], "ok")
        self.assertEqual(checks["forge.permissions"]["permissions"], {"project_access": 30})
        self.assertIn("API", checks["forge.permissions"]["message"])
        self.assert_read_only_calls("gitlab.com")

    def test_missing_git_or_remote_is_optional_warning_but_strict_error(self):
        for missing in ("remote", "git"):
            with self.subTest(missing=missing):
                if missing == "git":
                    (self.tools / "git").unlink()
                self.assertEqual(self.report()["forge.target"]["status"], "warning")
                self.assertEqual(self.report("--require-forge", code=1)["forge.target"]["status"], "error")

    def test_missing_client_does_not_require_other_provider(self):
        self.remote()
        self.client("glab")
        self.assertEqual(self.report()["forge.cli"]["status"], "warning")
        self.assertEqual(self.report("--require-forge", code=1)["forge.cli"]["status"], "error")
        self.assertEqual(self.calls(), [])

    def test_multiple_remotes_require_explicit_selection(self):
        self.remote()
        self.remote("git@gitlab.com:group/sub/demo.git", "upstream")
        self.client("glab")
        self.assertEqual(self.report()["forge.target"]["status"], "warning")
        self.assertEqual(self.calls(), [])
        checks = self.report("--forge-remote", "upstream", "--require-forge")
        self.assertEqual(checks["forge.target"]["remote"], "upstream")

    def test_missing_named_remote_and_multiple_fetch_urls_are_ambiguous(self):
        self.remote()
        self.client()
        self.assertEqual(self.report("--forge-remote", "missing")["forge.target"]["status"], "warning")
        self.git("config", "--add", "remote.origin.url", "https://github.com/other/demo.git")
        checks = self.report("--require-forge", code=1)
        self.assertEqual(checks["forge.target"]["reason"], "ambiguous_urls")
        self.assertEqual(self.calls(), [])

    def test_corporate_host_requires_provider_override(self):
        self.remote("git@code.example.test:group/sub/demo.git")
        responses = self.client("glab")
        responses["/user"]["web_url"] = "https://code.example.test/reader"
        responses["projects/group%2Fsub%2Fdemo"]["web_url"] = "https://code.example.test/group/sub/demo"
        self.client("glab", responses)
        self.assertEqual(self.report()["forge.target"]["status"], "warning")
        self.assertEqual(self.calls(), [])
        checks = self.report("--forge-provider", "gitlab", "--require-forge")
        self.assertEqual(checks["forge.target"]["host"], "code.example.test")
        self.assert_read_only_calls("code.example.test")

    def test_nested_cwd_and_project_choose_target_not_toolkit(self):
        self.remote()
        self.client()
        nested = self.root / "nested"
        nested.mkdir()
        self.assertEqual(self.report(cwd=nested)["forge.target"]["repository"], "team/demo")
        self.assertEqual(self.report("--project", str(self.root), cwd=self.tools)["forge.target"]["repository"], "team/demo")

    def test_project_without_git_boundary_never_uses_parent_remote(self):
        self.remote()
        self.client()
        child = self.root / "child"
        child.mkdir()
        for directory in ("knowledge", "raw"):
            (child / directory).mkdir()
        (child / "knowledge/SCHEMA.md").write_text("# Schema\n")
        (child / "knowledge/index.md").write_text("# Index\n")
        self.assertEqual(self.report("--project", str(child))["forge.target"]["status"], "warning")
        self.assertEqual(self.calls(), [])

    def test_git_worktree_dot_git_file_is_supported(self):
        self.remote()
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "--allow-empty", "-m", "Fixture")
        worktree = self.root.parent / "linked"
        self.git("worktree", "add", "--detach", str(worktree))
        for directory in ("knowledge", "raw"):
            (worktree / directory).mkdir()
        (worktree / "knowledge/SCHEMA.md").write_text("# Schema\n")
        (worktree / "knowledge/index.md").write_text("# Index\n")
        self.client()
        self.assertTrue((worktree / ".git").is_file())
        target = self.report("--project", str(worktree))["forge.target"]
        self.assertEqual(target["status"], "ok")
        self.assertEqual(target["repository"], "team/demo")

    def test_relative_path_clients_resolve_before_project_cwd_change(self):
        self.remote()
        self.client()
        self.env["PATH"] = "tools"
        checks = self.report("--project", str(self.root), cwd=self.root.parent)
        self.assertEqual(checks["forge.cli"]["status"], "ok")
        self.assertEqual(checks["forge.cli"]["path"], str(self.tools / "gh"))

    def test_invalid_version_and_executable_error_do_not_echo_secrets(self):
        self.remote()
        self.client(version="ghp_DO_NOT_PRINT http://token:secret@host/ version invalid")
        result = self.doctor()
        self.assertNotIn("ghp_DO_NOT_PRINT", result.stdout + result.stderr)
        self.assertNotIn("token:secret", result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["exit_code"], 0)
        self.assertEqual(self.report()["forge.cli"]["reason"], "invalid_version")
        (self.tools / "gh").write_text("#!/missing/runtime-secret\n")
        result = self.doctor("--require-forge")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("runtime-secret", result.stdout + result.stderr)

    def test_noninteractive_environment_strips_target_and_debug_overrides(self):
        self.remote()
        self.client()
        overrides = {"GH_HOST": "wrong.host", "GH_REPO": "secret/repo", "GLAB_REPO": "secret/repo",
                     "GITLAB_HOST": "wrong.host", "GH_DEBUG": "api", "DEBUG": "true",
                     "GH_PAGER": "secret-pager", "GLAB_PAGER": "secret-pager", "PAGER": "secret-pager",
                     "GIT_DIR": "secret-dir", "GIT_WORK_TREE": "secret-worktree",
                     "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "remote.origin.url",
                     "GIT_CONFIG_VALUE_0": "https://wrong.example/secret/repo.git",
                     "GITLAB_REPO": "secret/repo", "GITLAB_API_HOST": "wrong.host", "GLAB_DEBUG_HTTP": "true",
                     "GLAB_API_PROTOCOL": "http", "API_PROTOCOL": "http", "GITLAB_SUBFOLDER": "unexpected/path",
                     "GITLAB_URI": "wrong.host"}
        self.env.update(overrides)
        self.env["GLAB_ENABLE_CI_AUTOLOGIN"] = "true"
        self.env["GH_TOKEN"] = "ghp_TOKEN_MUST_STAY_PRIVATE"
        checks = self.report("--require-forge")
        self.assertEqual(checks["forge.repository"]["status"], "ok")
        for call in self.calls():
            for key in overrides:
                self.assertNotIn(key, call["env"])
            self.assertEqual(call["env"]["GH_PROMPT_DISABLED"], "1")
            self.assertEqual(call["env"]["GLAB_ENABLE_CI_AUTOLOGIN"], "false")
        self.assertNotIn("ghp_TOKEN_MUST_STAY_PRIVATE", json.dumps(checks))

    def test_credential_query_and_fragment_remote_values_are_never_reported(self):
        for url in ("https://user:SECRET@example.test/team/demo.git", "https://github.com/team/demo.git?token=SECRET",
                    "https://github.com/team/demo.git#SECRET", "git@github.com:team/SECRET?token=secret.git"):
            with self.subTest(url=url):
                self.git("config", "remote.origin.url", url)
                result = self.doctor()
                self.assertNotIn("SECRET", result.stdout + result.stderr)
                checks = json.loads(result.stdout)["checks"]
                target = next(check for check in checks if check["id"] == "forge.target")
                self.assertEqual(target["status"], "warning")

    def test_auth_wrong_host_is_not_readiness(self):
        self.remote()
        responses = self.client()
        responses["/user"]["html_url"] = "https://wrong.example/reader"
        self.client(responses=responses)
        checks = self.report("--require-forge", code=1)
        self.assertEqual(checks["forge.auth"]["reason"], "identity_mismatch")
        self.assertEqual(checks["forge.repository"]["status"], "skipped")

    def test_repository_wrong_name_or_web_host_fails_identity_validation(self):
        self.remote()
        for field, value in (("full_name", "other/repo"), ("html_url", "https://wrong.example/team/demo")):
            with self.subTest(field=field):
                responses = self.client()
                responses["repos/team/demo"][field] = value
                self.client(responses=responses)
                checks = self.report("--require-forge", code=1)
                self.assertEqual(checks["forge.repository"]["reason"], "identity_mismatch")
                self.assertEqual(checks["forge.issues"]["status"], "skipped")

    def test_http_failures_and_network_errors_are_distinct_without_raw_error(self):
        self.remote()
        for status, reason in ((401, "unauthorized"), (403, "forbidden"), (404, "not_found"), (None, "client_error")):
            with self.subTest(status=status):
                responses = self.client()
                responses["/user"] = {"_returncode": 1, "_stderr": f"HTTP {status} ghp_SECRET token=SECRET"}
                self.client(responses=responses)
                checks = self.report("--require-forge", code=1)
                self.assertEqual(checks["forge.auth"]["reason"], reason)
                self.assertNotIn("SECRET", json.dumps(checks))

    def test_api_invalid_json_and_wrong_shapes_are_distinct(self):
        self.remote()
        for endpoint, value, reason in (("/user", {"_stdout": "not json SECRET"}, "invalid_json"),
                                       ("/user", [], "invalid_response"),
                                       ("repos/team/demo/issues?per_page=1", {}, "invalid_response"),
                                       ("repos/team/demo/pulls?per_page=1", ["SECRET"], "invalid_response")):
            with self.subTest(endpoint=endpoint, reason=reason):
                responses = self.client()
                responses[endpoint] = value
                self.client(responses=responses)
                checks = self.report("--require-forge", code=1)
                identifier = {"/user": "auth", "repos/team/demo/issues?per_page=1": "issues",
                              "repos/team/demo/pulls?per_page=1": "pull_requests"}[endpoint]
                self.assertEqual(checks["forge." + identifier]["reason"], reason)
                self.assertNotIn("SECRET", json.dumps(checks))

    def test_disabled_features_are_not_readiness(self):
        for provider, url, endpoint, field, identifier in (
                ("gh", "git@github.com:team/demo.git", "repos/team/demo", "has_issues", "issues"),
                ("glab", "git@gitlab.com:group/sub/demo.git", "projects/group%2Fsub%2Fdemo", "issues_enabled", "issues"),
                ("glab", "git@gitlab.com:group/sub/demo.git", "projects/group%2Fsub%2Fdemo", "merge_requests_enabled", "pull_requests")):
            with self.subTest(field=field):
                self.git("config", "remote.origin.url", url)
                responses = self.client(provider)
                responses[endpoint][field] = False
                self.client(provider, responses)
                checks = self.report("--require-forge", code=1)
                self.assertEqual(checks["forge." + identifier]["reason"], "feature_disabled")

    def test_gitlab_access_levels_and_github_permissions_are_allowlisted(self):
        for provider, url, endpoint, permissions in (
                ("gh", "git@github.com:team/demo.git", "repos/team/demo", {"pull": True, "push": "SECRET", "secret": "SECRET"}),
                ("glab", "git@gitlab.com:group/sub/demo.git", "projects/group%2Fsub%2Fdemo", {"project_access": {"access_level": "SECRET"}, "group_access": {"access_level": 999}})):
            with self.subTest(provider=provider):
                self.git("config", "remote.origin.url", url)
                responses = self.client(provider)
                responses[endpoint]["permissions"] = permissions
                self.client(provider, responses)
                checks = self.report("--require-forge")
                self.assertNotIn("SECRET", json.dumps(checks))
                self.assertNotIn("999", json.dumps(checks["forge.permissions"]))
                self.assertEqual(checks["forge.write"]["status"], "skipped")

    def test_timeout_is_bounded_and_does_not_expose_output(self):
        self.remote()
        responses = self.client()
        responses["/user"] = {"_sleep": 3, "_stdout": "SECRET"}
        self.client(responses=responses)
        checks = self.report("--forge-network", "--timeout", "1")
        self.assertEqual(checks["forge.auth"]["reason"], "timeout")
        self.assertEqual(checks["forge.auth"]["status"], "warning")
        self.assertNotIn("SECRET", json.dumps(checks))

    def test_text_and_json_both_show_selection_version_and_permissions(self):
        self.remote()
        self.client()
        checks = self.report("--forge-network")
        text = self.doctor("--forge-network", json_output=False).stdout
        for value in ("origin", "github.com", "team/demo", "2.80.0", "API", "pull", "push"):
            self.assertIn(value, text)
        for check in checks.values():
            if check["id"].startswith("forge."):
                self.assertIn(check["message"], text)

    def test_glab_actual_version_format_is_recognized(self):
        self.remote("git@gitlab.com:group/sub/demo.git")
        self.client("glab", version="glab 1.89.0 (c6fca530)")
        self.assertEqual(self.report()["forge.cli"]["version"], "1.89.0")

    def test_gh_distribution_version_metadata_is_accepted_without_echoing_suffix(self):
        self.remote()
        for suffix in ("2025-01-13 Debian 2.46.0-3", "2025-01-13 Ubuntu 2.46.0-1ubuntu0.2",
                       "2025-01-13 Debian ghp_DO_NOT_PRINT token=SECRET https://user:password@host"):
            with self.subTest(suffix=suffix):
                self.client(version=f"gh version 2.46.0 ({suffix})")
                checks = self.report()
                self.assertEqual(checks["forge.cli"]["status"], "ok")
                self.assertEqual(checks["forge.cli"]["version"], "2.46.0")
                text = self.doctor(json_output=False).stdout
                for output in (json.dumps(checks), text):
                    self.assertNotIn(suffix, output)
                    self.assertNotIn("ghp_DO_NOT_PRINT", output)
                    self.assertNotIn("SECRET", output)
                    self.assertNotIn("user:password", output)

    def test_gh_unstructured_version_suffix_remains_invalid(self):
        self.remote()
        for version in ("gh version 2.46.0 unstructured SECRET", "gh version SECRET (2025-01-13 Debian)",
                        "gh version 2.46.0 (2025-01-13 Debian) SECRET"):
            with self.subTest(version=version):
                self.client(version=version)
                checks = self.report()
                self.assertEqual(checks["forge.cli"]["reason"], "invalid_version")
                self.assertNotIn("SECRET", json.dumps(checks))

    def test_gitlab_http_status_in_client_error_is_classified(self):
        self.remote("git@gitlab.com:group/sub/demo.git")
        for status, label, reason in ((401, "Unauthorized", "unauthorized"), (403, "Forbidden", "forbidden"),
                                      (404, "Not Found", "not_found")):
            with self.subTest(status=status):
                responses = self.client("glab")
                responses["/user"] = {"_returncode": 1, "_stderr": f"GET https://gitlab.com/api/v4/user: {status} {label} SECRET"}
                self.client("glab", responses)
                checks = self.report("--require-forge", code=1)
                self.assertEqual(checks["forge.auth"]["reason"], reason)
                self.assertNotIn("SECRET", json.dumps(checks))

    def test_repository_and_list_http_errors_have_independent_checks(self):
        self.remote()
        for endpoint, identifier in (("repos/team/demo", "repository"),
                                     ("repos/team/demo/issues?per_page=1", "issues"),
                                     ("repos/team/demo/pulls?per_page=1", "pull_requests")):
            with self.subTest(identifier=identifier):
                responses = self.client()
                responses[endpoint] = {"_returncode": 1, "_stderr": "HTTP 403 SECRET"}
                self.client(responses=responses)
                checks = self.report("--require-forge", code=1)
                self.assertEqual(checks["forge." + identifier]["reason"], "forbidden")
                if identifier == "issues":
                    self.assertEqual(checks["forge.pull_requests"]["status"], "ok")

    def test_api_network_error_and_gitlab_wrong_identity_do_not_echo_fields(self):
        self.remote("git@gitlab.com:group/sub/demo.git")
        responses = self.client("glab")
        responses["/user"] = {"_returncode": 1, "_stderr": "dial tcp: no such host token SECRET"}
        self.client("glab", responses)
        self.assertEqual(self.report("--require-forge", code=1)["forge.auth"]["reason"], "network_error")
        for field, value in (("path_with_namespace", "secret/repo"), ("web_url", "https://wrong.example/SECRET")):
            with self.subTest(field=field):
                responses = self.client("glab")
                responses["projects/group%2Fsub%2Fdemo"][field] = value
                self.client("glab", responses)
                checks = self.report("--require-forge", code=1)
                self.assertEqual(checks["forge.repository"]["reason"], "identity_mismatch")
                self.assertNotIn("SECRET", json.dumps(checks))

    def test_client_version_nonzero_and_timeout_are_distinct(self):
        self.remote()
        client = self.tools / "gh"
        for code, expected in (("import sys; print('SECRET'); sys.exit(4)", "client_error"),
                               ("import time; time.sleep(3)", "timeout")):
            with self.subTest(reason=expected):
                client.write_text(f"#!{sys.executable}\n{code}\n")
                client.chmod(0o755)
                checks = self.report("--require-forge", "--timeout", "1", code=1)
                self.assertEqual(checks["forge.cli"]["reason"], expected)
                self.assertNotIn("SECRET", json.dumps(checks))

    def test_readiness_does_not_depend_on_permissions_payload(self):
        self.remote()
        responses = self.client()
        responses["repos/team/demo"]["permissions"] = {"SECRET": "SECRET"}
        responses["repos/team/demo/issues?per_page=1"] = [{"id": 1, "number": 1, "body": "SECRET"}]
        responses["repos/team/demo/pulls?per_page=1"] = [{"id": 2, "number": 2, "body": "SECRET"}]
        self.client(responses=responses)
        checks = self.report("--require-forge")
        self.assertEqual(checks["forge.permissions"]["status"], "skipped")
        self.assertNotIn("SECRET", json.dumps(checks))

    def test_https_default_and_corporate_api_ports_preserve_selected_authority(self):
        self.remote("https://github.com:443/team/demo.git")
        self.client()
        self.assertEqual(self.report("--require-forge")["forge.target"]["host"], "github.com")
        self.git("config", "remote.origin.url", "https://code.example.test:8443/group/sub/demo.git")
        responses = self.client("glab")
        responses["/user"]["web_url"] = "https://code.example.test:8443/reader"
        responses["projects/group%2Fsub%2Fdemo"]["web_url"] = "https://code.example.test:8443/group/sub/demo"
        self.client("glab", responses)
        self.log.unlink()
        checks = self.report("--forge-provider", "gitlab", "--require-forge")
        self.assertEqual(checks["forge.target"]["host"], "code.example.test:8443")
        self.assert_read_only_calls("code.example.test:8443")

    def test_github_nondefault_https_ports_are_rejected_before_client_invocation(self):
        self.remote()
        self.client()
        for host in ("github.com", "ghe.example"):
            self.git("config", "remote.origin.url", f"https://{host}:8443/team/demo.git")
            provider = () if host == "github.com" else ("--forge-provider", "github")
            for mode, code, status in (((), 0, "warning"), (("--forge-network",), 0, "warning"),
                                       (("--require-forge",), 1, "error")):
                with self.subTest(host=host, mode=mode):
                    self.log.unlink(missing_ok=True)
                    checks = self.report(*provider, *mode, code=code)
                    target = checks["forge.target"]
                    self.assertEqual(target["status"], status)
                    self.assertEqual(target["reason"], "unsupported_port")
                    self.assertIn("gh", target["message"])
                    self.assertIn("443", target["message"])
                    self.assertIn("remedy", target)
                    for name in ("cli", "auth", "repository", "issues", "pull_requests", "permissions", "write"):
                        self.assertEqual(checks["forge." + name]["status"], "skipped")
                    self.assertEqual(self.calls(), [])

    def test_github_enterprise_default_https_port_uses_hostname_without_port(self):
        self.remote("https://ghe.example:443/team/demo.git")
        responses = self.client()
        responses["/user"]["html_url"] = "https://ghe.example/reader"
        responses["repos/team/demo"]["html_url"] = "https://ghe.example/team/demo"
        self.client(responses=responses)
        checks = self.report("--forge-provider", "github", "--require-forge")
        self.assertEqual(checks["forge.target"]["host"], "ghe.example")
        self.assertEqual(checks["forge.repository"]["status"], "ok")
        self.assert_read_only_calls("ghe.example")

    def test_github_ssh_transport_port_does_not_become_api_port(self):
        self.remote()
        self.client()
        for port in (22, 2222):
            with self.subTest(port=port):
                self.log.unlink(missing_ok=True)
                self.git("config", "remote.origin.url", f"ssh://git@github.com:{port}/team/demo.git")
                checks = self.report("--require-forge")
                self.assertEqual(checks["forge.target"]["host"], "github.com")
                self.assertEqual(checks["forge.repository"]["status"], "ok")
                self.assert_read_only_calls("github.com")

    def test_github_identity_names_are_case_insensitive(self):
        self.remote("git@github.com:Team/Demo.git")
        responses = self.client()
        for endpoint in list(responses):
            if endpoint.startswith("repos/"):
                responses[endpoint.replace("repos/team/demo", "repos/Team/Demo")] = responses.pop(endpoint)
        self.client(responses=responses)
        self.assertEqual(self.report("--require-forge")["forge.repository"]["status"], "ok")

    def test_worktree_specific_remote_is_included(self):
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "--allow-empty", "-m", "Fixture")
        self.git("config", "extensions.worktreeConfig", "true")
        worktree = self.root.parent / "linked"
        self.git("worktree", "add", "--detach", str(worktree))
        self.git("config", "--worktree", "remote.origin.url", "git@github.com:team/demo.git", root=worktree)
        for directory in ("knowledge", "raw"):
            (worktree / directory).mkdir()
        (worktree / "knowledge/SCHEMA.md").write_text("# Schema\n")
        (worktree / "knowledge/index.md").write_text("# Index\n")
        self.client()
        target = self.report("--project", str(worktree))["forge.target"]
        self.assertEqual(target["status"], "ok")
        self.assertEqual(target["repository"], "team/demo")

    def test_global_git_remote_does_not_become_project_target(self):
        self.remote()
        self.git("config", "--global", "remote.toolkit.url", "https://github.com/toolkit/upstream.git")
        self.client()
        target = self.report()["forge.target"]
        self.assertEqual(target["status"], "ok")
        self.assertEqual(target["repository"], "team/demo")

    def test_api_lists_require_object_identifiers_for_both_providers(self):
        for provider, url, endpoint in (("gh", "git@github.com:team/demo.git", "repos/team/demo/issues?per_page=1"),
                                       ("glab", "git@gitlab.com:group/sub/demo.git", "projects/group%2Fsub%2Fdemo/merge_requests?per_page=1")):
            self.git("config", "remote.origin.url", url)
            for value in ({}, {"message": "SECRET"}, {"id": True, "number": 1, "iid": 1}):
                with self.subTest(provider=provider, value=value):
                    responses = self.client(provider)
                    responses[endpoint] = [value]
                    self.client(provider, responses)
                    checks = self.report("--require-forge", code=1)
                    name = "issues" if provider == "gh" else "pull_requests"
                    self.assertEqual(checks["forge." + name]["reason"], "invalid_response")
                    self.assertNotIn("SECRET", json.dumps(checks))

    def test_remote_value_cannot_inject_a_second_scoped_record(self):
        self.remote("https://github.com/team/demo.git\nworktree remote.hijack.url https://github.com/other/repo.git")
        self.client()
        target = self.report("--forge-remote", "hijack")["forge.target"]
        self.assertEqual(target["status"], "warning")
        self.assertEqual(self.calls(), [])

    def test_invalid_ssh_port_is_rejected_before_client_calls(self):
        self.remote("ssh://git@github.com:SECRET/team/demo.git")
        self.client()
        target = self.report()["forge.target"]
        self.assertEqual(target["status"], "warning")
        self.assertEqual(self.calls(), [])

    def test_online_diagnostics_preserve_target_bytes_and_mtimes(self):
        self.remote()
        self.client()
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.root.rglob("*") if path.is_file()}
        self.report("--require-forge")
        after = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_gitlab_ambient_api_routing_overrides_are_removed(self):
        self.remote("git@gitlab.com:group/sub/demo.git")
        self.client("glab")
        for name, value in (("GLAB_API_PROTOCOL", "http"), ("API_PROTOCOL", "http"),
                            ("GITLAB_SUBFOLDER", "unexpected/path"), ("GITLAB_URI", "wrong.host")):
            with self.subTest(variable=name):
                self.log.unlink(missing_ok=True)
                self.env[name] = value
                try:
                    checks = self.report("--require-forge")
                finally:
                    self.env.pop(name)
                self.assertEqual(checks["forge.repository"]["status"], "ok")
                for call in self.calls():
                    self.assertNotIn(name, call["env"])

    def test_gitlab_ci_autologin_is_explicitly_disabled(self):
        self.remote("git@gitlab.com:group/sub/demo.git")
        self.client("glab")
        self.env.update({"GLAB_ENABLE_CI_AUTOLOGIN": "true", "GITLAB_CI": "true"})
        self.report("--require-forge")
        for call in self.calls():
            self.assertEqual(call["env"]["GLAB_ENABLE_CI_AUTOLOGIN"], "false")
