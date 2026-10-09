"""Deterministic, read-only lint of raw unit root envelopes."""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from _core import Finding, WikiError, discover_repository, is_within, profile_path, relative_path, wiki_layout
from _okf import OKF_COMMIT, OKF_VERSION, concept_findings, yaml_module

SLUG = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')
UNIT = re.compile(r'(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)\Z')
LIMITATIONS = [
    'Проверены только корневые README.md выбранных raw-единиц, не весь OKF bundle и оригинальные вложения.',
    'Не проверены истинность claims, полнота текста, права verifier, свежесть, runtime или аттестация.',
    'Внешние URL и скрипты из метаданных не открываются и не выполняются; файлы не изменяются.',
]


def safe_path(path, root, findings):
    try:
        if is_within(path.resolve(), root.resolve()):
            return True
    except (OSError, RuntimeError):
        pass
    findings.append(Finding('error', 'E_RAW_ESCAPE', path, 'Путь или symlink выходит за пределы checkout'))
    return False


def children(path, root, findings):
    if not safe_path(path, root, findings):
        return []
    try:
        return sorted(path.iterdir(), key=lambda child: child.name)
    except OSError:
        findings.append(Finding('error', 'E_RAW_READ', path, 'Нельзя прочитать каталог raw'))
        return []


def discover_units(root, layout, findings):
    units = []
    categories = [profile_path(root, layout.raw, name, 'raw_categories') for name in layout.raw_categories]
    if not layout.raw.is_dir():
        findings.append(Finding('error', 'E_RAW_READ', layout.raw, 'Не найден каталог raw_root'))
        return units
    category_roots = {path.absolute() for path in categories}
    for entry in children(layout.raw, root, findings):
        if entry.name not in ('README.md', 'index.md', 'log.md') and entry.absolute() not in category_roots:
            findings.append(Finding('warning', 'W_RAW_UNSCANNED', entry,
                                    'Материал вне выбранных категорий; legacy не мигрирует и не проверен автоматически'))
    for name, category in zip(layout.raw_categories, categories):
        if not category.exists() and not category.is_symlink():
            continue
        for topic in children(category, root, findings):
            if not safe_path(topic, root, findings):
                continue
            if topic.is_symlink():
                findings.append(Finding('warning', 'W_RAW_UNSCANNED', topic, 'Symlink-каталог темы не обходится автоматически'))
                continue
            if not topic.is_dir():
                if topic.name not in ('README.md', 'index.md', 'log.md'):
                    findings.append(Finding('warning', 'W_RAW_UNSCANNED', topic, 'Файл вне единицы: дерево требует topic/unit/README.md'))
                continue
            for unit in children(topic, root, findings):
                if not safe_path(unit, root, findings):
                    continue
                if unit.is_dir():
                    units.append((unit / 'README.md', name))
                elif unit.name not in ('README.md', 'index.md', 'log.md'):
                    findings.append(Finding('warning', 'W_RAW_UNSCANNED', unit, 'Файл вне единицы: legacy сохранён без преобразования'))
    return units


def explicit_units(root, layout, paths):
    units = []
    for value in paths:
        path = Path(value)
        path = Path.cwd() / path if not path.is_absolute() else path
        # Normalize lexical .. while preserving the path to inspect symlinks.
        import os
        path = Path(os.path.abspath(path))
        if not is_within(path, layout.raw.absolute()) or not is_within(path.resolve(), layout.raw.resolve()):
            raise WikiError('Явный путь должен находиться внутри raw_root и checkout')
        if path.name != 'README.md':
            if path.exists() and not path.is_dir():
                raise WikiError('Явный путь должен быть каталогом единицы или её README.md')
            path = path / 'README.md'
        relative = path.relative_to(layout.raw.absolute())
        category = relative.parts[0] if len(relative.parts) > 1 else ''
        units.append((path, category))
    return units


def tree_findings(path, raw, findings):
    relative = path.relative_to(raw.absolute())
    parts = relative.parts
    valid = len(parts) == 4 and parts[-1] == 'README.md' and bool(SLUG.fullmatch(parts[1]))
    match = UNIT.fullmatch(parts[-2]) if len(parts) >= 2 else None
    if match:
        try:
            date.fromisoformat(match[1])
        except ValueError:
            match = None
    if not valid or not match:
        findings.append(Finding('error', 'E_RAW_TREE', path,
                                'Дерево raw: category/topic/YYYY-MM-DD-slug/README.md; topic/slug — lowercase-kebab-case'))


def lint_report(root, layout, paths, okf_only):
    findings = []
    candidates = explicit_units(root, layout, paths) if paths else discover_units(root, layout, findings)
    units = sorted(set(candidates), key=lambda pair: relative_path(pair[0], root))
    if units:
        yaml_module()
    checked = []
    for path, category in units:
        if not safe_path(path, root, findings):
            continue
        if not path.is_file():
            findings.append(Finding('error', 'E_RAW_ROOT', path, 'Единица должна иметь корневой README.md'))
            continue
        if not okf_only:
            tree_findings(path, layout.raw, findings)
        checked.append(relative_path(path, root))
        findings.extend(concept_findings(path, root, category, okf_only=okf_only))
    findings.sort(key=lambda finding: (*finding.sort_key(root), finding.message))
    errors = sum(finding.severity == 'error' for finding in findings)
    warnings = sum(finding.severity == 'warning' for finding in findings)
    return {
        'project': str(root), 'raw_root': relative_path(layout.raw, root),
        'raw_categories': list(layout.raw_categories), 'mode': 'okf' if okf_only else 'raw',
        'okf_version': OKF_VERSION, 'spec_commit': OKF_COMMIT,
        'checked': checked,
        'findings': [{'severity': f.severity, 'code': f.code, 'path': relative_path(f.path, root),
                      'line': f.line, 'message': f.message} for f in findings],
        'summary': {'errors': errors, 'warnings': warnings, 'checked': len(checked)},
        'limitations': LIMITATIONS, 'exit_code': 1 if errors else 0,
    }


def main():
    parser = argparse.ArgumentParser(description='Read-only OKF/raw lint of unit root README.md')
    parser.add_argument('paths', nargs='*', help='unit directories or README.md within raw_root')
    parser.add_argument('--json', action='store_true', help='stable JSON report')
    parser.add_argument('--okf-only', action='store_true', help='concept conformance; raw policy is not applied')
    args = parser.parse_args()
    try:
        root = discover_repository(validate=False)
        layout = wiki_layout(root)
        report = lint_report(root, layout, args.paths, args.okf_only)
    except (WikiError, OSError, RuntimeError, UnicodeError, ValueError) as exc:
        report = {'checked': [], 'findings': [], 'summary': {'errors': 1, 'warnings': 0, 'checked': 0},
                  'error': str(exc), 'limitations': LIMITATIONS, 'exit_code': 2}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for finding in report['findings']:
            location = finding['path'] + (f":{finding['line']}" if finding['line'] else '')
            print(f"{finding['severity']} {finding['code']} {location}: {finding['message']}")
        if 'error' in report:
            print('Ошибка инструмента: ' + report['error'])
        summary = report['summary']
        print(f"Raw README.md: {summary['checked']}; ошибки: {summary['errors']}; предупреждения: {summary['warnings']}")
        for limitation in report['limitations']:
            print(limitation)
    return report['exit_code']
