import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = PROJECT_ROOT / "bin" / "wiki"


class WikiCliTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(self.temporary_directory.name)
        self.root = temporary_root / "repository"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        for directory in ("raw", "knowledge", "openspec"):
            (self.root / directory).mkdir()
        (self.root / "README.md").write_text("# Проект\n", encoding="utf-8")
        (self.root / "AGENTS.md").write_text("# Инструкции\n", encoding="utf-8")
        self.write("knowledge/GLOSSARY.md", "# Глоссарий\n\n## Видео\n\nВидеоматериал.\n")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write(self, relative_path: str, content: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def run_cli(self, command: str, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(BIN_DIR / command), *arguments],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )


class LinkLintTest(WikiCliTestCase):
    def test_accepts_existing_relative_link(self):
        self.write("knowledge/target.md", "# Цель\n")
        self.write("knowledge/source.md", "[Цель](target.md)\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("блокирующих ошибок", result.stdout)

    def test_reports_broken_relative_link_with_source_line(self):
        self.write("knowledge/source.md", "Первая строка\n[Нет](missing.md)\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 1)
        self.assertIn("E_LINK_MISSING", result.stdout)
        self.assertIn("knowledge/source.md:2", result.stdout)

    def test_accepts_fragment_only_anchor(self):
        self.write("knowledge/source.md", "# Раздел\n[Выше](#раздел)\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_accepts_external_url(self):
        self.write("knowledge/source.md", "[Источник](https://example.com/a#b)\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_accepts_angle_bracket_path_with_spaces(self):
        self.write("knowledge/path with spaces.md", "# Пробелы\n")
        self.write("knowledge/source.md", "[Файл](<path with spaces.md>)\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_accepts_percent_encoded_path_with_spaces(self):
        self.write("knowledge/path with spaces.md", "# Пробелы\n")
        self.write("knowledge/source.md", "[Файл](path%20with%20spaces.md)\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_accepts_nested_relative_link(self):
        self.write("knowledge/domains/source/overview.md", "[Цель](../target/page.md)\n")
        self.write("knowledge/domains/target/page.md", "# Цель\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rejects_lexical_path_escape(self):
        outside = self.root.parent / "outside.md"
        outside.write_text("# Снаружи\n", encoding="utf-8")
        self.write("knowledge/source.md", "[Снаружи](../../outside.md)\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 1)
        self.assertIn("E_LINK_ESCAPE", result.stdout)

    def test_rejects_symlink_path_escape(self):
        outside = self.root.parent / "outside.md"
        outside.write_text("# Снаружи\n", encoding="utf-8")
        link = self.root / "knowledge" / "outside-link.md"
        link.symlink_to(outside)
        self.write("knowledge/source.md", "[Снаружи](outside-link.md)\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 1)
        self.assertIn("E_LINK_ESCAPE", result.stdout)

    def test_rejects_windows_absolute_local_path(self):
        self.write("knowledge/source.md", "[Локальный файл](C:\\temp\\file.md)\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 1)
        self.assertIn("E_LINK_ABSOLUTE", result.stdout)

    def test_ignores_link_example_inside_fenced_code(self):
        self.write("knowledge/source.md", "```markdown\n[Пример](missing.md)\n```\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class DecisionLintTest(WikiCliTestCase):
    def test_accepts_valid_decision_filename(self):
        self.write("knowledge/decisions/2026-09-valid-decision.md", "# Решение\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rejects_invalid_decision_month(self):
        self.write("knowledge/decisions/2026-13-invalid.md", "# Решение\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 1)
        self.assertIn("E_DECISION_NAME", result.stdout)

    def test_rejects_non_kebab_decision_filename(self):
        self.write("knowledge/decisions/Bad_Name.md", "# Решение\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 1)
        self.assertIn("E_DECISION_NAME", result.stdout)

    def test_does_not_apply_decision_rule_outside_decisions(self):
        self.write("knowledge/domains/topic/Bad_Name.md", "# Знание\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class CanonicalTitleLintTest(WikiCliTestCase):
    def test_rejects_duplicate_h1_inside_same_domain(self):
        self.write("knowledge/domains/video/one.md", "# Одинаковый заголовок\n")
        self.write("knowledge/domains/video/two.md", "#  одинаковый   заголовок \n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 1)
        self.assertIn("E_DOMAIN_H1_DUPLICATE", result.stdout)
        self.assertIn("knowledge/domains/video/one.md", result.stdout)
        self.assertIn("knowledge/domains/video/two.md", result.stdout)

    def test_allows_same_h1_in_different_domains(self):
        self.write("knowledge/domains/video/page.md", "# Общий заголовок\n")
        self.write("knowledge/domains/users/page.md", "# Общий заголовок\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class SemanticIndexLintTest(WikiCliTestCase):
    def test_warns_when_domain_page_is_missing_from_semantic_index(self):
        self.write("knowledge/index.md", "# Индекс\n")
        self.write("knowledge/domains/video/page.md", "# Видео\n")

        result = self.run_cli("lint")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("W_INDEX_MISSING", result.stdout)
        self.assertIn("knowledge/domains/video/page.md", result.stdout)


class OrphanCommandTest(WikiCliTestCase):
    def test_reports_orphan_but_not_linked_page(self):
        self.write(
            "knowledge/index.md",
            "# Индекс\n[Связанная](domains/topic/linked.md)\n",
        )
        self.write("knowledge/domains/topic/linked.md", "# Связанная\n")
        self.write("knowledge/domains/topic/orphan.md", "# Сирота\n")

        result = self.run_cli("find-orphans")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("knowledge/domains/topic/orphan.md", result.stdout)
        self.assertNotIn("knowledge/domains/topic/linked.md", result.stdout)

    def test_exempts_top_level_semantic_pages(self):
        for filename in (
            "SCHEMA.md",
            "README.md",
            "index.md",
            "synthesis.md",
            "OPEN-QUESTIONS.md",
            "ASSUMPTIONS.md",
            "GLOSSARY.md",
            "log.md",
        ):
            self.write(f"knowledge/{filename}", f"# {filename}\n")

        result = self.run_cli("find-orphans")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Страницы-сироты: 0", result.stdout)


class AffectedCommandTest(WikiCliTestCase):
    SOURCE = "raw/technology/source.md"

    def setUp(self):
        super().setUp()
        self.write(self.SOURCE, "# Источник\n")

    def test_finds_direct_markdown_link(self):
        self.write(
            "knowledge/domains/video/page.md",
            "[Источник](../../../raw/technology/source.md)\n",
        )

        result = self.run_cli("affected", self.SOURCE)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("прямая-ссылка", result.stdout)
        self.assertIn("knowledge/domains/video/page.md", result.stdout)

    def test_finds_plain_repository_path(self):
        self.write("knowledge/domains/video/page.md", f"См. `{self.SOURCE}`.\n")

        result = self.run_cli("affected", self.SOURCE)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("путь", result.stdout)
        self.assertIn("knowledge/domains/video/page.md", result.stdout)

    def test_finds_plain_basename(self):
        self.write("knowledge/domains/video/page.md", "См. source.md.\n")

        result = self.run_cli("affected", self.SOURCE)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("имя-файла", result.stdout)
        self.assertIn("knowledge/domains/video/page.md", result.stdout)

    def test_finds_plain_phrase_case_insensitively(self):
        self.write("knowledge/domains/video/page.md", "Решение о СУБТИТРАХ.\n")

        result = self.run_cli("affected", "решение о субтитрах")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("фраза", result.stdout)
        self.assertIn("knowledge/domains/video/page.md", result.stdout)

    def test_requires_one_query_argument(self):
        result = self.run_cli("affected")

        self.assertEqual(result.returncode, 2)
        self.assertIn("Использование", result.stderr)


class StatusCommandTest(WikiCliTestCase):
    def test_prints_required_counts_in_stable_order(self):
        self.write("raw/technology/source.md", "# Источник\n")
        self.write("knowledge/domains/video/page.md", "# Домен\n")
        self.write("knowledge/product/page.md", "# Продукт\n")
        self.write("knowledge/sales/page.md", "# Продажи\n")
        self.write("knowledge/architecture/page.md", "# Архитектура\n")
        self.write("knowledge/decisions/2026-09-choice.md", "# Решение\n")
        self.write("knowledge/inbox/idea.md", "# Идея\n")

        result = self.run_cli("status")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        labels = [
            "Первичные источники:",
            "Страницы знаний:",
            "Доменные страницы:",
            "Представление architecture:",
            "Представление product:",
            "Представление sales:",
            "Решения:",
            "Страницы входящих идей:",
            "Сломанные ссылки:",
            "Страницы-сироты:",
        ]
        offsets = [result.stdout.index(label) for label in labels]
        self.assertEqual(offsets, sorted(offsets))


if __name__ == "__main__":
    unittest.main()
