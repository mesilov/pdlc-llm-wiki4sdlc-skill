#!/usr/bin/env python3
"""Детерминированное ядро Git-native wiki harness."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


SCAN_FILES = ("README.md", "AGENTS.md")
DECISION_NAME_RE = re.compile(
    r"^\d{4}-(?:0[1-9]|1[0-2])-[a-z0-9]+(?:-[a-z0-9]+)*\.md$"
)
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\n]+)\)")
REFERENCE_DEFINITION_RE = re.compile(r"^ {0,3}\[((?:\\.|[^\]\\])+)\]:[ \t]*(.+)$")
REFERENCE_LINK_RE = re.compile(
    r"(?<!\\)!?\[((?:\\.|[^\]\\\n])+)\](?:[ \t]*\[((?:\\.|[^\]\\\n])*)\])?"
)
INLINE_CODE_RE = re.compile(r"(`+)(.*?)\1")
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
FENCE_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})(.*)$")
EXTERNAL_SCHEMES = {"data", "ftp", "http", "https", "mailto", "tel"}


class WikiError(RuntimeError):
    """Контролируемая ошибка вызова harness."""


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    path: Path
    message: str
    line: int | None = None

    def sort_key(self, root: Path) -> tuple[str, str, int, str]:
        return (
            self.severity,
            relative_path(self.path, root),
            self.line or 0,
            self.code,
        )

    def render(self, root: Path) -> str:
        location = relative_path(self.path, root)
        if self.line is not None:
            location = f"{location}:{self.line}"
        label = "ОШИБКА" if self.severity == "error" else "ПРЕДУПРЕЖДЕНИЕ"
        return f"{label} {self.code} {location}: {self.message}"


@dataclass(frozen=True)
class LinkReference:
    source: Path
    line: int
    destination: str
    target: Path | None
    finding: Finding | None


def relative_path(path: Path, root: Path) -> str:
    try:
        return path.absolute().relative_to(root.absolute()).as_posix()
    except ValueError:
        return path.as_posix()


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


DOCUMENT_DEFAULTS = {
    "schema": "SCHEMA.md", "index": "index.md", "synthesis": "synthesis.md",
    "assumptions": "ASSUMPTIONS.md", "open_questions": "OPEN-QUESTIONS.md",
    "glossary": "GLOSSARY.md", "log": "log.md",
}
LAYER_DEFAULTS = {
    "domains": "domains", "views": "views", "decisions": "decisions", "inbox": "inbox", "archive": "archive",
}
DEFAULT_VIEWS = (
    "product", "discovery", "experience", "engineering",
    "go-to-market", "operations", "measurement",
)
DEFAULT_RAW_CATEGORIES = ("sources", "research")


@dataclass(frozen=True)
class WikiLayout:
    corpus: Path
    raw: Path
    knowledge: Path
    openspec: Path | None
    documents: dict[str, Path | None]
    layers: dict[str, Path]
    scan_files: tuple[Path, ...]
    decision_pattern: re.Pattern
    glossary_sort: str
    views: tuple[str, ...]
    raw_categories: tuple[str, ...]


def profile_path(root: Path, base: Path, value: str, key: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise WikiError(f"{key} должен быть непустым относительным путём")
    relative = Path(value)
    if relative.is_absolute() or WINDOWS_ABSOLUTE_RE.match(value) or ".." in relative.parts:
        raise WikiError(f"{key} должен быть путём внутри checkout")
    path = base / relative
    if not is_within(path.resolve(strict=False), base.resolve()):
        raise WikiError(f"{key} выходит за границу своего корня через symlink")
    if not is_within(path.resolve(strict=False), root.resolve()):
        raise WikiError(f"{key} выходит за границу repository через symlink")
    return path


def wiki_layout(root: Path) -> WikiLayout:
    profile = root / "wiki.config.json"
    if not is_within(profile.resolve(strict=False), root.resolve()):
        raise WikiError("wiki.config.json выходит за границу repository")
    values = {}
    if profile.exists():
        try:
            values = json.loads(profile.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            raise WikiError(f"неверный wiki.config.json: {error}") from error
    allowed = {"corpus_root", "raw_root", "knowledge_root", "openspec_root", "documents",
               "layers", "scan_files", "decision_name_pattern", "glossary_sort",
               "project_name", "context", "language", "decision_statuses", "views", "raw_categories"}
    if not isinstance(values, dict) or set(values) - allowed:
        raise WikiError("wiki.config.json: неизвестные поля или неверный JSON object")
    for key in ("project_name", "context", "language"):
        if key in values and (not isinstance(values[key], str) or not values[key].strip()):
            raise WikiError(f"{key} должен быть непустой строкой")
    for key in ("decision_statuses", "views", "raw_categories"):
        if key in values and (not isinstance(values[key], list) or
                              not all(isinstance(item, str) and item.strip() for item in values[key])):
            raise WikiError(f"{key} должен быть списком непустых строк")
    for category in values.get("raw_categories", DEFAULT_RAW_CATEGORIES):
        if category in {".", ".."} or any(character in category for character in ("/", "\\", "\x00")):
            raise WikiError("raw_categories: нужны имена категорий одного уровня, без . или .., разделителей пути и NUL")
    corpus = profile_path(root, root, values.get("corpus_root", "."), "corpus_root")
    raw = profile_path(root, root, values["raw_root"], "raw_root") if "raw_root" in values else profile_path(root, corpus, "raw", "raw_root")
    knowledge = profile_path(root, root, values["knowledge_root"], "knowledge_root") if "knowledge_root" in values else profile_path(root, corpus, "knowledge", "knowledge_root")
    spec_value = values.get("openspec_root")
    openspec = None if spec_value is None else profile_path(root, root, spec_value, "openspec_root")
    if not knowledge.is_dir():
        raise WikiError("не найден корень знаний: " + relative_path(knowledge, root))
    if openspec is not None and not openspec.is_dir():
        raise WikiError("подключённый каталог OpenSpec отсутствует: " + relative_path(openspec, root))
    roots = [raw, knowledge] + ([openspec] if openspec is not None else [])
    for i, first in enumerate(roots):
        for second in roots[i + 1:]:
            if is_within(first.resolve(), second.resolve()) or is_within(second.resolve(), first.resolve()):
                raise WikiError("OpenSpec, raw и knowledge должны иметь отдельные корни")
    mappings = []
    for key, defaults in (("documents", DOCUMENT_DEFAULTS), ("layers", LAYER_DEFAULTS)):
        overrides = values.get(key, {})
        if not isinstance(overrides, dict) or set(overrides) - set(defaults):
            raise WikiError(f"{key}: неизвестные поля или неверный JSON object")
        resolved = {}
        for name, default in defaults.items():
            value = overrides.get(name, default)
            if value is None and key == "documents" and name not in {"schema", "index"}:
                resolved[name] = None
            else:
                resolved[name] = profile_path(root, knowledge, value, f"{key}.{name}")
        active = [path.resolve() for path in resolved.values() if path is not None]
        if len(active) != len(set(active)):
            raise WikiError(f"{key}: пути не должны совпадать")
        if key == "layers":
            for i, first in enumerate(active):
                for second in active[i + 1:]:
                    if is_within(first, second) or is_within(second, first):
                        raise WikiError("layers: каталоги не должны пересекаться")
        mappings.append(resolved)
    scans = values.get("scan_files", list(SCAN_FILES))
    if not isinstance(scans, list):
        raise WikiError("scan_files должен быть списком путей")
    scan_files = tuple(profile_path(root, root, value, "scan_files") for value in scans)
    pattern = values.get("decision_name_pattern", DECISION_NAME_RE.pattern)
    if not isinstance(pattern, str) or not pattern:
        raise WikiError("decision_name_pattern должен быть непустой строкой")
    try:
        decision_pattern = re.compile(pattern)
    except re.error as error:
        raise WikiError(f"неверный decision_name_pattern: {error}") from error
    sort = values.get("glossary_sort", "latin-cyrillic")
    if sort not in ("latin-cyrillic", "unicode"):
        raise WikiError("glossary_sort: допустимы latin-cyrillic или unicode")
    views = tuple(values.get("views", DEFAULT_VIEWS))
    raw_categories = tuple(values.get("raw_categories", DEFAULT_RAW_CATEGORIES))
    return WikiLayout(corpus, raw, knowledge, openspec, *mappings, scan_files, decision_pattern, sort, views, raw_categories)


def discover_repository(start: Path | None = None, *, validate: bool = True) -> Path:
    current = (start or Path.cwd()).absolute()
    if current.is_file():
        current = current.parent
    candidates = (current, *current.parents)
    # Граница Git/config имеет приоритет над вложенными raw/knowledge.
    for candidate in candidates:
        if (candidate / ".git").exists() or (candidate / "wiki.config.json").exists():
            if validate:
                wiki_layout(candidate)
            return candidate
    for candidate in candidates:
        if (candidate / "knowledge").is_dir() and (candidate / "raw").is_dir():
            if validate:
                wiki_layout(candidate)
            return candidate
    raise WikiError("не найден корень wiki repository; запустите команду из checkout")


def candidate_markdown_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    layout = wiki_layout(root)
    for path in layout.scan_files:
        if path.is_file():
            files.add(path)
    for directory in (layout.raw, layout.knowledge, layout.openspec):
        if directory is not None and directory.is_dir():
            files.update(directory.rglob("*.md"))
    return sorted(files, key=lambda path: relative_path(path, root))


def markdown_files(root: Path) -> list[Path]:
    resolved_root = root.resolve()
    return [
        path
        for path in candidate_markdown_files(root)
        if is_within(path.resolve(strict=False), resolved_root)
    ]


def unsafe_markdown_findings(root: Path) -> list[Finding]:
    resolved_root = root.resolve()
    return [
        Finding(
            "error",
            "E_FILE_ESCAPE",
            path,
            "Markdown-файл разрешается за границу репозитория через symlink",
        )
        for path in candidate_markdown_files(root)
        if not is_within(path.resolve(strict=False), resolved_root)
    ]


def without_code_lines(text: str, *, preserve_inline: bool = False) -> list[str]:
    result: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    fence_indent = 0
    indented_code = False
    paragraph = False
    list_indents: list[int] = []

    for line in text.splitlines():
        expanded = line.expandtabs(4)
        indent = len(expanded) - len(expanded.lstrip(' '))
        if fence_character is not None:
            fence = FENCE_RE.match(expanded[fence_indent:] if indent >= fence_indent else expanded)
            if (fence and fence.group(1)[0] == fence_character
                    and len(fence.group(1)) >= fence_length and not fence.group(2).strip()):
                fence_character = None
                fence_length = 0
            result.append('')
            continue

        if not line.strip():
            result.append('')
            paragraph = False
            continue

        # A continuation is indented relative to its list item, not the page.
        # Four spaces can therefore be ordinary list text, rather than code.
        while list_indents and indent < list_indents[-1]:
            list_indents.pop()
        container_indent = list_indents[-1] if list_indents else 0
        if indent - container_indent >= 4 and (indented_code or not paragraph):
            result.append('')
            indented_code = True
            continue
        indented_code = False

        marker = re.match(r"^ *(?:[-+*]|\d{1,9}[.)]) +(?=\S)", expanded)
        if marker and indent - container_indent < 4:
            list_indents.append(marker.end())
            paragraph = True
        content_line = expanded[container_indent:]
        fence = FENCE_RE.match(content_line)
        if fence:
            marker = fence.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            fence_indent = container_indent
            paragraph = False
            result.append('')
            continue

        # An indented block cannot interrupt a prose paragraph. Headings,
        # reference definitions and separators end that paragraph instead.
        paragraph = not bool(re.match(
            r"^ {0,3}(?:#{1,6}(?:\s|$)|\[[^\]]+\]:|(?:[-*_] *){3,}$)", content_line
        ))
        result.append(line if preserve_inline else INLINE_CODE_RE.sub("", line))

    return result


def link_destination(raw_destination: str) -> str:
    destination = raw_destination.strip()
    if destination.startswith("<") and ">" in destination:
        return destination[1 : destination.index(">")]
    return destination.split(maxsplit=1)[0]


def iter_link_destinations(path: Path) -> list[tuple[int, str]]:
    destinations: list[tuple[int, str]] = []
    text = path.read_text(encoding="utf-8")
    # Definitions retain quoted titles and inline code in file names; usages
    # exclude inline code. Both passes retain the original source line numbers.
    definition_lines = without_code_lines(text, preserve_inline=True)
    definitions: dict[str, str] = {}
    excluded: set[int] = set()
    for line_number, line in enumerate(definition_lines, start=1):
        match = REFERENCE_DEFINITION_RE.match(line)
        if match:
            label = normalized_reference_label(match.group(1))
            definitions.setdefault(label, link_destination(match.group(2)))
            excluded.add(line_number)
    for line_number, line in enumerate(without_code_lines(text), start=1):
        if line_number in excluded:
            continue
        inline_spans = []
        for match in LINK_RE.finditer(line):
            destinations.append((line_number, link_destination(match.group(1))))
            inline_spans.append(match.span())
        for match in REFERENCE_LINK_RE.finditer(line):
            if any(start < match.end() and match.start() < end for start, end in inline_spans):
                continue
            label = normalized_reference_label(match.group(2) or match.group(1))
            if label in definitions:
                destinations.append((line_number, definitions[label]))
    return destinations


def normalized_reference_label(label: str) -> str:
    label = re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])", r"\1", label)
    return " ".join(label.casefold().split())


def resolve_link(root: Path, source: Path, line: int, destination: str) -> LinkReference:
    if not destination or destination.startswith("#"):
        return LinkReference(source, line, destination, None, None)

    if (
        destination.startswith("/")
        or WINDOWS_ABSOLUTE_RE.match(destination)
    ):
        finding = Finding(
            "error",
            "E_LINK_ABSOLUTE",
            source,
            f"абсолютная локальная ссылка запрещена: {destination}",
            line,
        )
        return LinkReference(source, line, destination, None, finding)

    parsed = urlsplit(destination)
    scheme = parsed.scheme.casefold()
    if (scheme and scheme != "file") or destination.startswith("//"):
        return LinkReference(source, line, destination, None, None)

    if scheme == "file":
        finding = Finding(
            "error",
            "E_LINK_ABSOLUTE",
            source,
            f"абсолютная локальная ссылка запрещена: {destination}",
            line,
        )
        return LinkReference(source, line, destination, None, finding)

    target_text = unquote(parsed.path).replace("\\ ", " ")
    if not target_text:
        return LinkReference(source, line, destination, None, None)

    candidate = source.parent / target_text
    resolved_root = root.resolve()
    resolved_target = candidate.resolve(strict=False)
    if not is_within(resolved_target, resolved_root):
        finding = Finding(
            "error",
            "E_LINK_ESCAPE",
            source,
            f"локальная ссылка выходит за границу репозитория: {destination}",
            line,
        )
        return LinkReference(source, line, destination, None, finding)

    if not candidate.exists():
        finding = Finding(
            "error",
            "E_LINK_MISSING",
            source,
            f"цель не существует: {destination}",
            line,
        )
        return LinkReference(source, line, destination, resolved_target, finding)

    if resolved_target.is_dir():
        readme = resolved_target / "README.md"
        if readme.is_file():
            resolved_target = readme.resolve()

    return LinkReference(source, line, destination, resolved_target, None)


def link_references(root: Path, files: list[Path] | None = None) -> list[LinkReference]:
    references: list[LinkReference] = []
    for source in files or markdown_files(root):
        for line, destination in iter_link_destinations(source):
            references.append(resolve_link(root, source, line, destination))
    return references


def link_findings(root: Path) -> list[Finding]:
    findings = unsafe_markdown_findings(root)
    findings.extend(
        reference.finding
        for reference in link_references(root)
        if reference.finding is not None
    )
    return findings


def decision_findings(root: Path) -> list[Finding]:
    layout = wiki_layout(root)
    decisions = layout.layers["decisions"]
    if not decisions.is_dir():
        return []
    return [
        Finding(
            "error",
            "E_DECISION_NAME",
            path,
            f"имя решения должно соответствовать {layout.decision_pattern.pattern}",
        )
        for path in sorted(decisions.rglob("*.md"))
        if not layout.decision_pattern.fullmatch(path.name)
    ]


def first_h1(path: Path) -> str | None:
    for line in without_code_lines(path.read_text(encoding="utf-8")):
        if line.startswith("# "):
            return " ".join(line[2:].split()).casefold()
    return None


def duplicate_h1_findings(root: Path) -> list[Finding]:
    domains = wiki_layout(root).layers["domains"]
    if not domains.is_dir():
        return []
    grouped: dict[tuple[str, str], list[Path]] = {}
    for path in sorted(domains.rglob("*.md")):
        if not is_within(path.resolve(strict=False), root.resolve()):
            continue
        relative = path.relative_to(domains)
        if len(relative.parts) < 2:
            continue
        title = first_h1(path)
        if title:
            grouped.setdefault((relative.parts[0], title), []).append(path)

    findings: list[Finding] = []
    for (_, title), paths in sorted(grouped.items()):
        if len(paths) < 2:
            continue
        all_paths = ", ".join(relative_path(path, root) for path in paths)
        for path in paths:
            findings.append(
                Finding(
                    "error",
                    "E_DOMAIN_H1_DUPLICATE",
                    path,
                    f"дублирующий H1 «{title}» внутри одного домена: {all_paths}",
                )
            )
    return findings


def knowledge_pages(root: Path) -> list[Path]:
    knowledge = wiki_layout(root).knowledge
    if not knowledge.is_dir():
        return []
    resolved_root = root.resolve()
    return [
        path
        for path in sorted(knowledge.rglob("*.md"))
        if is_within(path.resolve(strict=False), resolved_root)
    ]


def orphan_pages(root: Path) -> list[Path]:
    knowledge = wiki_layout(root).knowledge
    pages = knowledge_pages(root)
    resolved_to_page = {path.resolve(): path for path in pages}
    inbound: set[Path] = set()
    for reference in link_references(root, pages):
        if reference.finding is not None or reference.target is None:
            continue
        target = reference.target.resolve()
        if target in resolved_to_page and target != reference.source.resolve():
            inbound.add(target)

    supporting = {path.resolve() for path in wiki_layout(root).documents.values() if path is not None}
    supporting.add((knowledge / "README.md").resolve())
    orphans = []
    for page in pages:
        if page.resolve() in supporting:
            continue
        if page.resolve() not in inbound:
            orphans.append(page)
    return sorted(orphans, key=lambda path: relative_path(path, root))


def orphan_findings(root: Path) -> list[Finding]:
    return [
        Finding(
                "warning",
                "W_ORPHAN",
                path,
                "страница не имеет входящих ссылок из корпуса знаний",
        )
        for path in orphan_pages(root)
    ]


def semantic_index_findings(root: Path) -> list[Finding]:
    index = wiki_layout(root).documents["index"]
    if not index.is_file():
        return [
            Finding(
                "warning",
                "W_INDEX_MISSING_FILE",
                index,
                "семантический индекс отсутствует",
            )
        ]

    indexed_targets = {
        reference.target.resolve()
        for reference in link_references(root, [index])
        if reference.finding is None and reference.target is not None
    }
    canonical_roots = (
        wiki_layout(root).layers["domains"],
        wiki_layout(root).layers["decisions"],
    )
    findings: list[Finding] = []
    for canonical_root in canonical_roots:
        if not canonical_root.is_dir():
            continue
        for path in sorted(canonical_root.rglob("*.md")):
            if not is_within(path.resolve(strict=False), root.resolve()):
                continue
            if path.resolve() not in indexed_targets:
                findings.append(
                    Finding(
                        "warning",
                        "W_INDEX_MISSING",
                        path,
                        "каноническая страница не указана напрямую в semantic index",
                    )
                )
    return findings


@dataclass(frozen=True)
class GlossaryEntry:
    title: str
    line: int
    text: str
    body: str

    def normalized_title(self) -> str:
        title = INLINE_CODE_RE.sub(lambda match: match.group(2), self.title)
        return " ".join(unicodedata.normalize("NFC", title).casefold().split())

    def sort_key(self, order: str = "latin-cyrillic") -> tuple[int, str]:
        if order == "unicode":
            return 0, self.normalized_title()
        title = self.normalized_title().replace("ё", "е")
        first = title[:1]
        group = 0 if "a" <= first <= "z" else 1 if "а" <= first <= "я" else 2
        return group, title


def glossary_entries(text: str) -> tuple[str, list[GlossaryEntry]]:
    lines = text.splitlines(keepends=True)
    headings = []
    for index, line in enumerate(without_code_lines(text, preserve_inline=True)):
        match = re.match(r"^ {0,3}##(?:[ \t]+(.*)|[ \t]*)$", line)
        if match:
            title = re.sub(r"(?:^|[ \t]+)#+[ \t]*$", "", match.group(1) or "").strip()
            headings.append((index, title))
    entries = []
    for offset, (index, title) in enumerate(headings):
        end = headings[offset + 1][0] if offset + 1 < len(headings) else len(lines)
        entries.append(GlossaryEntry(
            title, index + 1, "".join(lines[index:end]), "".join(lines[index + 1:end])
        ))
    preamble = "".join(lines[:headings[0][0]]) if headings else text
    return preamble, entries


def glossary_findings(root: Path) -> list[Finding]:
    layout = wiki_layout(root)
    path = layout.documents["glossary"]
    if path is None:
        return []
    if not is_within(path.resolve(strict=False), root.resolve()):
        return []  # E_FILE_ESCAPE уже выдаётся общей проверкой.
    if not path.is_file():
        return [Finding("error", "E_GLOSSARY_MISSING", path, "глоссарий отсутствует")]
    _, entries = glossary_entries(path.read_bytes().decode("utf-8"))
    if not entries:
        return [Finding("error", "E_GLOSSARY_EMPTY", path, "нет записей H2", 1)]
    findings = []
    seen: dict[str, int] = {}
    previous: GlossaryEntry | None = None
    for entry in entries:
        title = entry.normalized_title()
        if not title or not entry.body.strip():
            findings.append(Finding(
                "error", "E_GLOSSARY_EMPTY", path,
                "запись должна иметь название и непустое определение", entry.line,
            ))
        if title in seen:
            findings.append(Finding(
                "error", "E_GLOSSARY_DUPLICATE", path,
                f"повтор заголовка «{entry.title}» из строки {seen[title]}; требуется разбор агентом",
                entry.line,
            ))
        seen.setdefault(title, entry.line)
        if previous is not None and entry.sort_key(layout.glossary_sort) < previous.sort_key(layout.glossary_sort):
            findings.append(Finding(
                "error", "E_GLOSSARY_ORDER", path,
                f"«{entry.title}» должно идти перед «{previous.title}»; используйте --fix",
                entry.line,
            ))
        previous = entry
    return findings


def fix_glossary_order(root: Path) -> bool:
    layout = wiki_layout(root)
    path = layout.documents["glossary"]
    if path is None:
        return False
    if any(part.is_symlink() for part in (path, *path.parents) if is_within(part, root)):
        raise WikiError("отказ записи глоссария через symlink")
    if not path.is_file():
        return False
    original = path.read_bytes()
    preamble, entries = glossary_entries(original.decode("utf-8"))
    ordered = sorted(entries, key=lambda entry: entry.sort_key(layout.glossary_sort))
    if ordered == entries:
        return False
    blocks = []
    newline = "\r\n" if b"\r\n" in original else "\n"
    for index, entry in enumerate(ordered):
        block = entry.text
        if index == len(ordered) - 1:
            block = block.rstrip("\r\n") + newline
        elif not block.endswith(newline * 2):
            block = block.rstrip("\r\n") + newline * 2
        blocks.append(block)
    updated = preamble + "".join(blocks)
    _, reparsed = glossary_entries(updated)
    expected = [(entry.title, entry.body.rstrip("\r\n")) for entry in ordered]
    actual = [(entry.title, entry.body.rstrip("\r\n")) for entry in reparsed]
    if actual != expected:
        raise WikiError(
            "сортировка меняет структуру глоссария; "
            "проверьте незакрытые блоки кода; файл не изменён"
        )
    path.write_bytes(updated.encode("utf-8"))
    return True


def lint_findings(root: Path) -> list[Finding]:
    from _trace import trace_findings

    findings = link_findings(root)
    findings.extend(decision_findings(root))
    findings.extend(duplicate_h1_findings(root))
    findings.extend(orphan_findings(root))
    findings.extend(semantic_index_findings(root))
    findings.extend(glossary_findings(root))
    findings.extend(trace_findings(root))
    return sorted(findings, key=lambda finding: finding.sort_key(root))


def count_markdown(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for path in directory.rglob("*.md") if path.is_file())


def repository_status(root: Path) -> list[tuple[str, int]]:
    link_errors = [
        finding for finding in link_findings(root) if finding.code == "E_LINK_MISSING"
    ]
    layout = wiki_layout(root)
    sections = [
        ("Первичные источники", count_markdown(layout.raw)),
        ("Страницы знаний", count_markdown(layout.knowledge)),
        ("Доменные страницы", count_markdown(layout.layers["domains"])),
    ]
    view_counts: dict[str, int] = {}
    view_directories = list(layout.knowledge.iterdir())
    layer_paths = [path.resolve() for path in layout.layers.values()]
    if layout.layers["views"].is_dir():
        view_directories.extend(layout.layers["views"].iterdir())
    for directory in view_directories:
        resolved = directory.resolve()
        if (directory.is_dir() and is_within(resolved, root.resolve())
                and not any(is_within(layer, resolved) for layer in layer_paths)):
            view_counts[directory.name] = view_counts.get(directory.name, 0) + count_markdown(directory)
    sections.extend((f"Представление {name}", count) for name, count in sorted(view_counts.items()))
    sections.extend([
        ("Решения", count_markdown(layout.layers["decisions"])),
        ("Страницы входящих идей", count_markdown(layout.layers["inbox"])),
        ("Сломанные ссылки", len(link_errors)),
        ("Страницы-сироты", len(orphan_pages(root))),
    ])
    return sections


def affected_documents(root: Path, query: str) -> dict[Path, set[str]]:
    query_path = Path(query)
    candidate = query_path if query_path.is_absolute() else root / query_path
    path_mode = candidate.exists()
    target: Path | None = None
    relative_query = ""
    basename = ""
    stem = ""

    if path_mode:
        target = candidate.resolve()
        if not is_within(target, root.resolve()):
            raise WikiError("указанный путь выходит за границу репозитория")
        relative_query = target.relative_to(root.resolve()).as_posix().casefold()
        basename = target.name.casefold()
        stem = target.stem.casefold()

    matches: dict[Path, set[str]] = {}
    for source in markdown_files(root):
        if target is not None and source.resolve() == target:
            continue
        text = source.read_text(encoding="utf-8")
        folded = text.casefold()
        types: set[str] = set()

        if target is not None:
            for reference in link_references(root, [source]):
                if (
                    reference.finding is None
                    and reference.target is not None
                    and reference.target.resolve() == target
                ):
                    types.add("прямая-ссылка")
            if relative_query and relative_query in folded:
                types.add("путь")
            if basename and basename in folded:
                types.add("имя-файла")
            if stem and stem != basename and stem in folded:
                types.add("основа-имени")
        elif query.casefold() in folded:
            types.add("фраза")

        if types:
            matches[source] = types

    return dict(sorted(matches.items(), key=lambda item: relative_path(item[0], root)))


def main_lint() -> int:
    arguments = sys.argv[1:]
    if arguments in (["--help"], ["-h"]):
        print("Использование: bin/wiki/lint [--dry-run | --fix]")
        print("Без флагов и с --dry-run: проверка без записи файлов.")
        print("--fix: сортировка записей глоссария и повторная проверка wiki.")
        return 0
    if arguments not in ([], ["--dry-run"], ["--fix"]):
        print("Использование: bin/wiki/lint [--dry-run | --fix]", file=sys.stderr)
        return 2
    try:
        root = discover_repository()
        if arguments == ["--fix"] and fix_glossary_order(root):
            print(f"Исправлено: {relative_path(wiki_layout(root).documents['glossary'], root)} (порядок записей)")
        findings = lint_findings(root)
    except (OSError, UnicodeError, WikiError) as error:
        print(f"Ошибка wiki-инструмента: {error}", file=sys.stderr)
        return 2

    errors = [finding for finding in findings if finding.severity == "error"]
    warnings = [finding for finding in findings if finding.severity == "warning"]
    print(f"Ошибки: {len(errors)}")
    for finding in errors:
        print(finding.render(root))
    print(f"Предупреждения: {len(warnings)}")
    for finding in warnings:
        print(finding.render(root))
    print(f"Итог: {len(errors)} блокирующих ошибок, {len(warnings)} предупреждений.")
    return 1 if errors else 0


def main_status() -> int:
    try:
        root = discover_repository()
        values = repository_status(root)
    except (OSError, UnicodeError, WikiError) as error:
        print(f"Ошибка wiki-инструмента: {error}", file=sys.stderr)
        return 2

    print("Состояние wiki")
    for label, value in values:
        print(f"{label}: {value}")
    return 0


def main_find_orphans() -> int:
    try:
        root = discover_repository()
        orphans = orphan_pages(root)
    except (OSError, UnicodeError, WikiError) as error:
        print(f"Ошибка wiki-инструмента: {error}", file=sys.stderr)
        return 2

    print(f"Страницы-сироты: {len(orphans)}")
    for path in orphans:
        print(f"- {relative_path(path, root)}")
    return 0


def main_affected(arguments: list[str]) -> int:
    if len(arguments) != 1 or not arguments[0].strip():
        print("Использование: bin/wiki/affected <path-or-phrase>", file=sys.stderr)
        return 2
    try:
        root = discover_repository()
        matches = affected_documents(root, arguments[0])
    except (OSError, UnicodeError, WikiError) as error:
        print(f"Ошибка wiki-инструмента: {error}", file=sys.stderr)
        return 2

    print(f"Затронутые документы: {len(matches)}")
    for path, types in matches.items():
        print(f"- [{', '.join(sorted(types))}] {relative_path(path, root)}")
    return 0
