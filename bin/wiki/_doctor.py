"""Read-only environment and profile diagnostics for an installed wiki kit."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

from _core import WikiError, discover_repository, is_within, wiki_layout


TOOLS = ("codex", "claude", "opencode")
LOCAL_SKILL_ROOTS = {
    "codex": (".agents/skills", ".codex/skills"),
    "claude": (".claude/skills",),
    "opencode": (".opencode/skills", ".agents/skills", ".claude/skills"),
}
NON_STRING_SCALAR = re.compile(
    r"[-+]?(?:[0-9][0-9_]*(?:\.[0-9_]*)?(?:[eE][-+]?[0-9]+)?|"
    r"\.[0-9]+(?:[eE][-+]?[0-9]+)?|0x[0-9a-f_]+|0o[0-7_]+|0b[01_]+|\.inf|\.nan)",
    re.IGNORECASE,
)
LIMITATION = (
    "Проверены пути и читаемость файлов skills, а не их загрузка, разрешения "
    "и настройки активной сессии агента, полнота workflow profile или смысл спецификации."
)


def add(checks, identifier, status, message, path=None, remedy=None, **details):
    check = {"id": identifier, "status": status, "message": message, **details}
    if path is not None:
        check["path"] = str(path)
    if remedy is not None:
        check["remedy"] = remedy
    checks.append(check)


def check_path(checks, identifier, path, kind, missing="error"):
    if path is None:
        add(checks, identifier, "skipped", "Путь отключён профилем")
        return
    try:
        if path.is_symlink() and not path.exists():
            raise ValueError("Битый symlink")
        if not path.exists():
            add(checks, identifier, missing, "Путь отсутствует", path,
                "Проверьте путь в wiki.config.json и восстановите ресурс" if missing != "skipped" else None)
            return
        if kind == "directory":
            if not path.is_dir():
                raise ValueError("Ожидался каталог")
            next(path.iterdir(), None)
        else:
            if not path.is_file():
                raise ValueError("Ожидался обычный файл")
            with path.open("rb") as stream:
                stream.read(1)
        add(checks, identifier, "ok", "Доступный " + ("каталог" if kind == "directory" else "файл"), path)
    except (ValueError, OSError, RuntimeError) as error:
        add(checks, identifier, "error", str(error), path,
            "Исправьте тип пути, symlink или права чтения")


def check_profile(root, checks, require_openspec):
    profile = root / "wiki.config.json"
    try:
        if profile.is_symlink() and not profile.exists():
            raise WikiError("Битый symlink wiki.config.json; fallback запрещён")
        layout = wiki_layout(root)
    except (WikiError, OSError, RuntimeError, UnicodeError) as error:
        add(checks, "profile", "error", str(error), profile,
            "Исправьте wiki.config.json и подключённые пути; fallback не применяется")
        add(checks, "openspec.root", "skipped", "Профиль не прошёл проверку")
        return None, True
    add(checks, "profile", "ok", "Профиль корректен" if profile.exists() else "Профиль отсутствует; используются defaults", profile)
    for name, path in (("corpus_root", layout.corpus), ("raw_root", layout.raw),
                       ("knowledge_root", layout.knowledge)):
        check_path(checks, f"path.{name}", path, "directory")
    for name, path in layout.documents.items():
        check_path(checks, f"path.documents.{name}", path, "file",
                   missing="error" if name in ("schema", "index") else "warning")
    for name, path in layout.layers.items():
        check_path(checks, f"path.layers.{name}", path, "directory", missing="skipped")
    for index, path in enumerate(layout.scan_files):
        check_path(checks, f"path.scan_files.{index}", path, "file", missing="warning")
    if layout.openspec is None:
        add(checks, "openspec.root", "error" if require_openspec else "skipped",
            "OpenSpec отключён: openspec_root не задан", profile,
            "Явно укажите openspec_root существующей интеграции в wiki.config.json" if require_openspec else None)
    else:
        check_path(checks, "openspec.root", layout.openspec, "directory")
    return layout, False


def check_cli(root, checks, severity, timeout):
    executable = shutil.which("openspec")
    remedy = "Установите OpenSpec CLI и добавьте исполняемый openspec в PATH"
    if executable is None:
        add(checks, "openspec.cli", severity, "OpenSpec CLI не найден в PATH", remedy=remedy)
        return
    # which() interprets relative PATH entries in the caller's cwd, before run() changes it.
    executable = str(Path(executable).absolute())
    try:
        result = subprocess.run([executable, "--version"], cwd=root,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout,
                                env={**os.environ, "DO_NOT_TRACK": "1"})
        output = (result.stdout or result.stderr).strip()
        version = re.search(r"\bv?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?\b", output)
        if result.returncode != 0:
            message = f"openspec --version завершился с кодом {result.returncode}: {output[:240]}"
        elif version is None:
            message = "openspec --version не вернул распознаваемую версию"
        else:
            add(checks, "openspec.cli", "ok", "OpenSpec CLI " + version.group(),
                executable, version=version.group())
            return
    except subprocess.TimeoutExpired:
        message = f"Таймаут openspec --version ({timeout:g} с)"
    except OSError as error:
        message = f"OpenSpec CLI не запускается: {error}"
    add(checks, "openspec.cli", severity, message, executable,
        "Проверьте OpenSpec CLI, его runtime и PATH")


def skill_roots(root, tool):
    home = Path.home()
    local = [(root / value, True, value == ".codex/skills") for value in LOCAL_SKILL_ROOTS[tool]]
    if tool == "codex":
        global_paths = (home / ".agents/skills",
                        Path(os.environ.get("CODEX_HOME") or home / ".codex") / "skills")
    elif tool == "claude":
        global_paths = (home / ".claude/skills",)
    else:
        global_paths = (Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "opencode/skills",
                        home / ".claude/skills", home / ".agents/skills")
    return local + [(path, False, False) for path in global_paths]


def validate_skill(path):
    """Check generated scalar/block headers; this is not a full YAML parser."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("SKILL.md должен начинаться с frontmatter ---")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise ValueError("Frontmatter SKILL.md не закрыт") from error
    header = lines[1:end]
    fields = {}
    for index, line in enumerate(header):
        match = re.fullmatch(r"(name|description):[ \t]*(.*)", line)
        if match is None:
            continue
        key, value = match.groups()
        if key in fields:
            raise ValueError(f"Повторное поле {key} в SKILL.md")
        if value in ("|", ">", "|-", ">-", "|+", ">+"):
            block = []
            for following in header[index + 1:]:
                if following and not following[0].isspace():
                    break
                block.append(following.strip())
            value = " ".join(block).strip()
        elif value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError as error:
                raise ValueError(f"Неверный quoted {key} в SKILL.md") from error
        elif value.startswith("'"):
            if len(value) < 2 or not value.endswith("'"):
                raise ValueError(f"Неверный quoted {key} в SKILL.md")
            value = value[1:-1].replace("''", "'")
        else:
            # Plain YAML scalars may be comments, null, booleans, numbers or collections.
            value = re.sub(r"(?:^|[ \t]+)#.*$", "", value).strip()
            if (value.lower() in ("null", "~", "true", "false") or
                    value.startswith(("[", "{", "&", "*", "!")) or
                    NON_STRING_SCALAR.fullmatch(value)):
                raise ValueError(f"{key} SKILL.md должен быть строкой")
        fields[key] = value
    name = fields.get("name")
    if not isinstance(name, str) or name != path.parent.name or not re.fullmatch(r"openspec-[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("name SKILL.md должен совпадать с каталогом openspec-*")
    description = fields.get("description")
    if not isinstance(description, str) or not description.strip() or description in ("null", "~"):
        raise ValueError("description SKILL.md должен быть непустым")
    if not "\n".join(lines[end + 1:]).strip():
        raise ValueError("Тело SKILL.md пустое")
    return name


def check_skills(root, tool, checks, severity):
    roots = skill_roots(root, tool)
    searched = [str(path) for path, _, _ in roots]
    found = []
    failures = 0
    for index, (directory, local, legacy) in enumerate(roots):
        identifier = f"openspec.skills.{tool}.root.{index}"
        try:
            if local and not is_within(directory.resolve(), root.resolve()):
                raise ValueError("Каталог skills выходит за checkout через symlink")
            if directory.is_symlink() and not directory.exists():
                raise ValueError("Битый symlink каталога skills")
            if not directory.exists():
                continue
            if not directory.is_dir():
                raise ValueError("Путь skills не является каталогом")
            candidates = sorted(path for path in directory.iterdir() if path.name.startswith("openspec-"))
        except (ValueError, OSError, RuntimeError) as error:
            failures += 1
            add(checks, identifier, severity, str(error), directory,
                "Исправьте каталог skills или его symlink")
            continue
        for candidate in candidates:
            path = candidate / "SKILL.md"
            try:
                if local and not is_within(path.resolve(), root.resolve()):
                    raise ValueError("Skill выходит за checkout через symlink")
                if candidate.is_symlink() and not candidate.exists():
                    raise ValueError("Битый symlink навыка")
                if path.is_symlink() and not path.exists():
                    raise ValueError("Битый symlink SKILL.md")
                name = validate_skill(path)
                found.append({"name": name, "path": str(path), "resolved_path": str(path.resolve()),
                              "scope": "project" if local else "user"})
                add(checks, f"{identifier}.{candidate.name}", "ok",
                    "Читаемый OpenSpec skill" + (" (legacy .codex/skills)" if legacy else ""), path)
            except (ValueError, OSError, RuntimeError, UnicodeError) as error:
                failures += 1
                add(checks, f"{identifier}.{candidate.name}", severity, str(error), path,
                    "Восстановите SKILL.md или исправьте symlink; openspec update выполняется отдельно")
    if failures:
        status, message = severity, f"{tool}: skills с проблемами: {failures}; читаемых: {len(found)}"
    elif found:
        status, message = "ok", f"{tool}: найдены читаемые OpenSpec skills ({len(found)})"
    else:
        status, message = severity, f"{tool}: OpenSpec skills не найдены в проверенных каталогах"
    add(checks, f"openspec.skills.{tool}", status, message,
        remedy=f"Проверьте skills выбранного агента; для установки в проект: openspec init --tools {tool}" if status != "ok" else None,
        searched=searched, skills=found)


def parse_tools(value):
    selected = tuple(dict.fromkeys(part.strip() for part in value.split(",")))
    if not selected or any(tool not in TOOLS for tool in selected):
        raise argparse.ArgumentTypeError("Допустимы codex,claude,opencode через запятую")
    return selected


def parse_timeout(value):
    try:
        timeout = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Таймаут должен быть числом секунд") from error
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("Таймаут должен быть положительным конечным числом")
    return timeout


def main_doctor(argv=None):
    parser = argparse.ArgumentParser(description="Самодиагностика путей wiki и OpenSpec CLI/skills без исправлений")
    parser.add_argument("--project", type=Path, help="корень целевого проекта вместо поиска из cwd")
    parser.add_argument("--tools", type=parse_tools, default=TOOLS, help="агенты через запятую (default: codex,claude,opencode)")
    parser.add_argument("--require-openspec", action="store_true", help="требовать подключение OpenSpec, CLI и skills")
    parser.add_argument("--timeout", type=parse_timeout, default=5.0, help="таймаут openspec --version в секундах (default: 5)")
    parser.add_argument("--json", action="store_true", help="структурированный отчёт")
    args = parser.parse_args(argv)
    checks = []
    root = None
    invalid_profile = False
    try:
        root = args.project.resolve() if args.project is not None else discover_repository(validate=False).resolve()
        if not root.is_dir():
            raise WikiError("Каталог проекта отсутствует: " + str(root))
    except (WikiError, OSError, RuntimeError) as error:
        add(checks, "project", "error", str(error), root,
            "Запустите doctor из целевого checkout или укажите --project PATH")
        invalid_profile = True
    else:
        layout, invalid_profile = check_profile(root, checks, args.require_openspec)
        required = args.require_openspec or (layout is not None and layout.openspec is not None)
        severity = "error" if required else "warning"
        check_cli(root, checks, severity, args.timeout)
        for tool in args.tools:
            check_skills(root, tool, checks, severity)
    summary = {status: sum(check["status"] == status for check in checks)
               for status in ("ok", "warning", "error", "skipped")}
    exit_code = 2 if invalid_profile else (1 if summary["error"] else 0)
    report = {"project": str(root) if root is not None else None, "tools": list(args.tools),
              "checks": checks, "summary": summary, "exit_code": exit_code, "limitations": LIMITATION}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("Самодиагностика wiki / OpenSpec: " + (str(root) if root is not None else "корень не найден"))
        labels = {"ok": "OK", "warning": "WARN", "error": "ERROR", "skipped": "SKIP"}
        for check in checks:
            print(f"[{labels[check['status']]}] {check['id']}: {check['message']}")
            if "path" in check:
                print("  Путь: " + check["path"])
            if "remedy" in check:
                print("  Действие: " + check["remedy"])
            if "searched" in check:
                print("  Поиск: " + "; ".join(check["searched"]))
        print(f"Ошибки: {summary['error']}; предупреждения: {summary['warning']}; код: {exit_code}")
        print(LIMITATION)
    return exit_code
