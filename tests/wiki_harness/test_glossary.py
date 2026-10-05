from tests.wiki_harness.test_cli import WikiCliTestCase


class GlossaryLintTest(WikiCliTestCase):
    def setUp(self):
        super().setUp()
        (self.root / "knowledge/GLOSSARY.md").unlink()

    def glossary(self, text):
        return self.write("knowledge/GLOSSARY.md", text)

    def test_check_and_dry_run_report_order_without_writing(self):
        path = self.glossary("# Глоссарий\n\n## Видео\n\nВидео.\n\n## Анализ\n\nАнализ.\n")
        before = path.read_bytes()
        modified = path.stat().st_mtime_ns
        check = self.run_cli("lint")
        dry_run = self.run_cli("lint", "--dry-run")
        self.assertEqual(check.returncode, 1)
        self.assertEqual(dry_run.returncode, check.returncode)
        self.assertEqual(check.stdout, dry_run.stdout)
        self.assertIn("E_GLOSSARY_ORDER knowledge/GLOSSARY.md:7", check.stdout)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_fix_preserves_blocks_preamble_and_code_and_is_idempotent(self):
        preamble = "# Глоссарий\n\nПояснение.\n\n"
        video = "## Видео (`Video`)\n\n[Источник](#источник)\n\n~~~md\n## ASR\n~~~\n\n"
        analysis = (
            "## Анализ (`Analysis`)\n\nАнализ.\n\n"
            "**Синонимы:** исследование — в контексте этой записи.\n\n"
            "**Избегать:** проверка — может обозначать другое понятие.\n\n"
            "**Контекст:** [Основание](../raw/source.md).\n\n"
            "### Детали\n\nТекст.\n\n"
        )
        asr = "## ASR\n\nРаспознавание.\n\n"
        path = self.glossary(preamble + video + analysis + asr)
        other = self.write("raw/source.md", "# Источник\n\nИсходный текст.\n")
        result = self.run_cli("lint", "--fix")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Исправлено: knowledge/GLOSSARY.md", result.stdout)
        self.assertNotIn("E_GLOSSARY_ORDER", result.stdout)
        self.assertEqual(path.read_text(), (preamble + asr + analysis + video).rstrip("\n") + "\n")
        self.assertEqual(other.read_text(), "# Источник\n\nИсходный текст.\n")
        modified = path.stat().st_mtime_ns
        again = self.run_cli("lint", "--fix")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertNotIn("Исправлено:", again.stdout)
        self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_sort_is_case_insensitive_and_places_yo_with_e(self):
        headings = ["ёж", "Ель", "Язык", "watch Inbox", "asr", "Анализ"]
        path = self.glossary("# Глоссарий\n\n" + "".join(f"## {h}\n\nТекст.\n\n" for h in headings))
        self.run_cli("lint", "--fix")
        actual = [line[3:] for line in path.read_text().splitlines() if line.startswith("## ")]
        self.assertEqual(actual, ["asr", "watch Inbox", "Анализ", "ёж", "Ель", "Язык"])

    def test_duplicates_and_empty_definitions_are_not_auto_fixed(self):
        original = "# Глоссарий\n\n## `ASR`\n\nРечь.\n\n## asr  \n\n"
        path = self.glossary(original)
        result = self.run_cli("lint", "--fix")
        self.assertEqual(result.returncode, 1)
        self.assertIn("E_GLOSSARY_DUPLICATE", result.stdout)
        self.assertIn("E_GLOSSARY_EMPTY", result.stdout)
        self.assertEqual(path.read_text(), original)

    def test_distinct_decision_and_verdict_are_not_duplicates(self):
        self.glossary("# Глоссарий\n\n## Решение (`Decision`)\n\nВыбор.\n\n## Решение (`Verdict`)\n\nДействие.\n")
        result = self.run_cli("lint")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fix_reports_remaining_broken_links_at_new_line(self):
        path = self.glossary("# Глоссарий\n\n## Видео\n\nВидео.\n\n## ASR\n\n[Нет](missing.md)\n\n")
        result = self.run_cli("lint", "--fix")
        self.assertEqual(result.returncode, 1)
        self.assertIn("E_LINK_MISSING knowledge/GLOSSARY.md:5", result.stdout)
        self.assertNotIn("E_GLOSSARY_ORDER", result.stdout)
        self.assertIn("[Нет](missing.md)", path.read_text())

    def test_invalid_arguments_do_not_modify_glossary(self):
        path = self.glossary("# Глоссарий\n\n## Видео\n\nВ.\n\n## ASR\n\nА.\n")
        original = path.read_bytes()
        for arguments in [("--unknown",), ("--fix", "--dry-run"), ("--fi",)]:
            with self.subTest(arguments=arguments):
                result = self.run_cli("lint", *arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(path.read_bytes(), original)

    def test_missing_glossary_is_reported_without_creation(self):
        result = self.run_cli("lint", "--fix")
        self.assertEqual(result.returncode, 1)
        self.assertIn("E_GLOSSARY_MISSING", result.stdout)
        self.assertFalse((self.root / "knowledge/GLOSSARY.md").exists())

    def test_glossary_without_entries_is_reported(self):
        path = self.glossary("# Глоссарий\n\nПояснение.\n")
        result = self.run_cli("lint", "--fix")
        self.assertEqual(result.returncode, 1)
        self.assertIn("E_GLOSSARY_EMPTY", result.stdout)
        self.assertEqual(path.read_text(), "# Глоссарий\n\nПояснение.\n")

    def test_fix_refuses_internal_and_external_symlink(self):
        for outside in (False, True):
            with self.subTest(outside=outside):
                target = (self.root.parent if outside else self.root) / "target.md"
                target.write_text("# Глоссарий\n\n## Я\n\nЯ.\n\n## А\n\nА.\n")
                original = target.read_bytes()
                path = self.root / "knowledge/GLOSSARY.md"
                path.symlink_to(target)
                result = self.run_cli("lint", "--fix")
                path.unlink()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(target.read_bytes(), original)
                self.assertIn("symlink", result.stdout + result.stderr)

    def test_last_block_without_newline_remains_separate_after_move(self):
        path = self.glossary("# Глоссарий\n\n## Я\n\nЯ.\n\n## А\n\nА.")
        result = self.run_cli("lint", "--fix")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("А.\n\n## Я", path.read_text())

    def test_inline_code_is_a_nonempty_definition(self):
        self.glossary("# Глоссарий\n\n## Verdict\n\n`skip`\n")
        result = self.run_cli("lint")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fix_refuses_symlink_parent(self):
        directory = self.root / "knowledge"
        target = self.root / "actual-knowledge"
        directory.rename(target)
        directory.symlink_to(target, target_is_directory=True)
        path = self.glossary("# Глоссарий\n\n## Я\n\nЯ.\n\n## А\n\nА.\n")
        before = path.read_bytes()
        result = self.run_cli("lint", "--fix")
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr)
        self.assertEqual(path.read_bytes(), before)

    def test_fix_preserves_crlf(self):
        path = self.glossary("")
        preamble = b"# Glossary\r\n\r\n"
        first = b"## Zebra\r\n\r\nZ.\r\n\r\n"
        last = b"## ASR\r\n\r\nA.\r\n"
        path.write_bytes(preamble + first + last)
        result = self.run_cli("lint", "--fix")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(path.read_bytes(), preamble + last + b"\r\n" + first.rstrip(b"\r\n") + b"\r\n")

    def test_moved_last_record_has_blank_separator_and_no_trailing_blank_line(self):
        path = self.glossary("# Глоссарий\n\n## Я\n\nЯ.\n\n## А\n\nА.\n")
        result = self.run_cli("lint", "--fix")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(path.read_text(), "# Глоссарий\n\n## А\n\nА.\n\n## Я\n\nЯ.\n")

    def test_fix_refuses_to_move_unclosed_fence_without_writing(self):
        path = self.glossary("# Глоссарий\n\n## Язык\n\nОпределение.\n\n## ASR\n\nРечь.\n\n```text\nпример\n")
        before = path.read_bytes()
        result = self.run_cli("lint", "--fix")
        self.assertEqual(result.returncode, 2)
        self.assertIn("структур", result.stderr)
        self.assertEqual(path.read_bytes(), before)

    def test_empty_atx_heading_with_closing_hashes_is_reported(self):
        self.glossary("# Глоссарий\n\n## ###\n\nТекст.\n")
        result = self.run_cli("lint")
        self.assertEqual(result.returncode, 1)
        self.assertIn("E_GLOSSARY_EMPTY", result.stdout)
