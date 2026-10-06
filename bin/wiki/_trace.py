"""Read-only, explicitly scoped wiki ↔ OpenSpec traceability checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from _core import (Finding, WikiError, discover_repository, is_within,
                   profile_path, relative_path, wiki_layout, without_code_lines)

ID = re.compile(r'^[A-Za-z][A-Za-z0-9._-]*$')
HEADING = re.compile(r'^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$')
ITEM = re.compile(r'^(Requirement|Scenario):\s*\[([A-Za-z][A-Za-z0-9._-]*)\]\s+\S.*$')


def object_fields(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise WikiError('неверные или отсутствующие поля JSON object: ' + ', '.join(required))


def nonempty(value):
    if not isinstance(value, str) or not value.strip():
        raise WikiError('ожидается непустая строка')
    return value


def strings(value, *, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise WikiError('ожидается список строк')
    for item in value:
        nonempty(item)
    if len(value) != len(set(value)):
        raise WikiError('повтор в списке строк')
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WikiError('повтор JSON-поля: ' + key)
        result[key] = value
    return result


def check_map(data):
    object_fields(data, ('version', 'feature', 'wiki_files', 'specs', 'decisions', 'links'), ('exclusions', 'review'))
    if type(data['version']) is not int or data['version'] != 1:
        raise WikiError('поддерживается version: 1')
    if not ID.fullmatch(nonempty(data['feature'])):
        raise WikiError('feature должен быть стабильным ASCII-идентификатором')
    strings(data['wiki_files'])
    strings(data['decisions'])
    if not isinstance(data['specs'], list) or not data['specs']:
        raise WikiError('specs должен содержать хотя бы один файл')
    spec_paths = []
    for spec in data['specs']:
        object_fields(spec, ('capability', 'path'))
        capability = nonempty(spec['capability'])
        if not ID.fullmatch(capability):
            raise WikiError('неверный capability')
        path = nonempty(spec['path'])
        if Path(path).parts[-3:] != ('specs', capability, 'spec.md'):
            raise WikiError('spec path должен заканчиваться specs/<capability>/spec.md')
        spec_paths.append(path)
    strings(spec_paths)
    if not isinstance(data['links'], list):
        raise WikiError('links должен быть списком')
    for link in data['links']:
        object_fields(link, ('requirement', 'scenario', 'wiki_requirements', 'wiki_scenarios'))
        for key in ('requirement', 'scenario'):
            if not ID.fullmatch(nonempty(link[key])):
                raise WikiError('неверный ID: ' + key)
        for key in ('wiki_requirements', 'wiki_scenarios'):
            for identifier in strings(link[key]):
                if not ID.fullmatch(identifier):
                    raise WikiError('неверный ID: ' + identifier)
    exclusions = data.get('exclusions', [])
    if not isinstance(exclusions, list):
        raise WikiError('exclusions должен быть списком')
    for exclusion in exclusions:
        object_fields(exclusion, ('id', 'reason'))
        if not ID.fullmatch(nonempty(exclusion['id'])):
            raise WikiError('неверный exclusion ID')
        nonempty(exclusion['reason'])
    review = data.get('review', {'status': 'pending'})
    object_fields(review, ('status',), ('reviewer', 'note', 'fingerprint'))
    if review['status'] not in ('pending', 'reviewed'):
        raise WikiError('review.status: допустимы pending и reviewed')
    if review['status'] == 'reviewed':
        for key in ('reviewer', 'note', 'fingerprint'):
            nonempty(review.get(key))


def source_file(root, base, name, layer=None):
    path = profile_path(root, base, name, 'trace source')
    if layer is not None and not is_within(path.resolve(), layer.resolve()):
        raise WikiError('источник должен находиться в настроенном слое: ' + relative_path(layer, base))
    if not path.is_file() or path.suffix != '.md':
        raise WikiError('не найден Markdown-источник: ' + relative_path(path, root))
    return path


def inventory(root, paths, issue):
    items = {}
    for path in paths:
        parent = None
        for line, text in enumerate(without_code_lines(path.read_text(encoding='utf-8'), preserve_inline=True), 1):
            heading = HEADING.match(text)
            if not heading:
                continue
            level, title = len(heading[1]), heading[2]
            if level <= 3:
                parent = None
            kind = 'requirement' if title.startswith('Requirement:') else (
                'scenario' if title.startswith('Scenario:') else None)
            if kind is None:
                continue
            expected_level = 3 if kind == 'requirement' else 4
            if level != expected_level:
                issue('E_TRACE_HEADING', f'{relative_path(path, root)}:{line}: {kind} требует H{expected_level}')
                continue
            match = ITEM.fullmatch(title)
            if not match:
                issue('E_TRACE_ID_MISSING', f'{relative_path(path, root)}:{line}: нужен заголовок {kind} со стабильным [ID]')
                continue
            identifier = match[2]
            if kind == 'requirement':
                parent = identifier
            elif parent is None:
                issue('E_TRACE_PARENT', f'{identifier}: Scenario не вложен в Requirement')
            if identifier in items:
                issue('E_TRACE_ID_DUPLICATE', 'повтор ID: ' + identifier)
                continue
            items[identifier] = {'kind': kind, 'parent': parent if kind == 'scenario' else None,
                                 'path': relative_path(path, root), 'line': line}
    for identifier, item in items.items():
        if item['kind'] == 'requirement' and not any(child['parent'] == identifier for child in items.values()):
            issue('E_TRACE_REQUIREMENT_EMPTY', 'у Requirement нет Scenario: ' + identifier)
    return items


def inspect_map(root, layout, path):
    result = {'feature': None, 'map': relative_path(path, root), 'issues': [], 'ready': False,
              'semantic_review': 'pending'}

    def issue(code, message, severity='error'):
        result['issues'].append({'severity': severity, 'code': code, 'map': result['map'], 'message': message})

    try:
        if not is_within(path.resolve(), layout.layers['domains'].resolve()):
            raise WikiError('карта выходит за границу domains через symlink')
        data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
        if isinstance(data, dict) and isinstance(data.get('feature'), str) and ID.fullmatch(data['feature']):
            result['feature'] = data['feature']
        check_map(data)
        wiki_paths = [source_file(root, layout.knowledge, name, layout.layers['domains']) for name in data['wiki_files']]
        spec_paths = [source_file(root, layout.openspec, spec['path']) for spec in data['specs']]
        decisions = [source_file(root, layout.knowledge, name, layout.layers['decisions']) for name in data['decisions']]
        # The declared files form the whole denominator; no implicit delta merge.
        result['scope'] = {key: data[key] for key in ('wiki_files', 'specs', 'decisions')}
        wiki = inventory(root, wiki_paths, issue)
        spec = inventory(root, spec_paths, issue)
        if not any(item['kind'] == 'scenario' for item in spec.values()):
            issue('E_TRACE_SCOPE_EMPTY', 'в объявленной спецификации нет Scenario для проверки')
        shared = set(wiki) & set(spec)
        for identifier in sorted(shared):
            issue('E_TRACE_ID_DUPLICATE', 'ID wiki и OpenSpec должны различаться: ' + identifier)
        excluded = set()
        for exclusion in data.get('exclusions', []):
            identifier = exclusion['id']
            if identifier not in wiki or identifier in excluded:
                issue('E_TRACE_EXCLUSION', 'неизвестное или повторное исключение: ' + identifier)
            excluded.add(identifier)
        covered, linked, seen = set(), set(), set()
        reverse = {identifier: [] for identifier in wiki}
        resolved_links = []

        def exists(identifier, items, kind):
            if identifier not in items or items[identifier]['kind'] != kind:
                issue('E_TRACE_ID', f'нет {kind} с ID {identifier}')
                return False
            return True

        for link in data['links']:
            sid, rid = link['scenario'], link['requirement']
            valid = True
            if sid in seen:
                issue('E_TRACE_LINK_DUPLICATE', 'повтор связи Scenario: ' + sid)
                valid = False
            seen.add(sid)
            scenario_exists = exists(sid, spec, 'scenario')
            requirement_exists = exists(rid, spec, 'requirement')
            valid &= scenario_exists and requirement_exists
            if scenario_exists and spec[sid]['parent'] != rid:
                issue('E_TRACE_PARENT', f'{sid} не принадлежит {rid}')
                valid = False
            for key, kind in (('wiki_requirements', 'requirement'), ('wiki_scenarios', 'scenario')):
                for identifier in link[key]:
                    valid &= exists(identifier, wiki, kind)
                    if identifier in excluded:
                        issue('E_TRACE_EXCLUSION', 'исключённый ID связан: ' + identifier)
                        valid = False
            for identifier in link['wiki_scenarios']:
                if identifier in wiki and wiki[identifier]['parent'] not in link['wiki_requirements']:
                    issue('E_TRACE_PARENT', f'{identifier}: нужен родительский wiki Requirement')
                    valid = False
            if valid:
                linked.add(sid)
                for identifier in link['wiki_requirements'] + link['wiki_scenarios']:
                    covered.add(identifier)
                    reverse[identifier].append(sid)
                resolved_links.append(dict(link, spec_source=spec[sid],
                                           wiki_sources={key: wiki[key] for key in link['wiki_requirements'] + link['wiki_scenarios']}))
        for identifier, item in spec.items():
            if item['kind'] == 'scenario' and identifier not in linked:
                issue('E_TRACE_SCENARIO_UNLINKED', 'нет корректной связи Scenario: ' + identifier)
        for identifier in sorted(set(wiki) - covered - excluded):
            issue('E_TRACE_WIKI_UNCOVERED', 'wiki ID не покрыт выбранным scope: ' + identifier)
        coverage = {}
        for kind in ('requirement', 'scenario'):
            spec_ids = {key for key, item in spec.items() if item['kind'] == kind}
            wiki_ids = {key for key, item in wiki.items() if item['kind'] == kind}
            traced = linked if kind == 'scenario' else {spec[key]['parent'] for key in linked}
            coverage['openspec_' + kind + 's'] = {'total': len(spec_ids), 'linked': len(spec_ids & traced)}
            coverage['wiki_' + kind + 's'] = {'total': len(wiki_ids), 'in_scope': len(wiki_ids - excluded),
                                             'covered': len(wiki_ids & covered), 'excluded': len(wiki_ids & excluded)}
        payload = {'definition': {key: value for key, value in data.items() if key != 'review'},
                   'files': {relative_path(p, root): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in wiki_paths + spec_paths + decisions}}
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
        review = data.get('review', {'status': 'pending'})
        state = review['status']
        if state == 'reviewed' and review['fingerprint'] != fingerprint:
            state = 'stale'
            issue('W_TRACE_REVIEW_STALE', 'файлы или карта изменились после смысловой проверки', 'warning')
        result.update(coverage=coverage, links=resolved_links, reverse=reverse,
                      exclusions=data.get('exclusions', []), fingerprint=fingerprint, semantic_review=state)
        result['ready'] = state == 'reviewed' and not any(item['severity'] == 'error' for item in result['issues'])
    except (WikiError, OSError, UnicodeError, ValueError) as error:
        issue('E_TRACE_SCHEMA', str(error))
    return result


def trace_report(root):
    layout = wiki_layout(root)
    if layout.openspec is None:
        raise WikiError('подключите OpenSpec явно: openspec_root в wiki.config.json')
    results = [inspect_map(root, layout, path) for path in sorted(layout.layers['domains'].rglob('traceability.json'))]
    by_feature = {}
    for result in results:
        if result['feature'] is not None:
            by_feature.setdefault(result['feature'], []).append(result)
    for feature, matches in by_feature.items():
        if len(matches) > 1:
            for result in matches:
                result['ready'] = False
                result['issues'].append({'severity': 'error', 'code': 'E_TRACE_FEATURE_DUPLICATE',
                                        'map': result['map'], 'message': 'повтор feature: ' + feature})
    return {'version': 1, 'checked_maps': len(results), 'features': results,
            'issues': [issue for result in results for issue in result['issues']]}


def trace_findings(root):
    if wiki_layout(root).openspec is None:
        return []
    return [Finding(item['severity'], item['code'], root / item['map'], item['message'])
            for item in trace_report(root)['issues']]


def main_trace():
    parser = argparse.ArgumentParser(description='Проверить трассировку wiki ↔ OpenSpec в объявленном scope')
    parser.add_argument('feature', nargs='?')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--require-reviewed', action='store_true')
    args = parser.parse_args()
    try:
        root = discover_repository()
        report = trace_report(root)
        if args.feature:
            selected = [item for item in report['features'] if item['feature'] == args.feature]
            if not selected:
                raise WikiError('не найдена карта feature: ' + args.feature)
            report.update(features=selected, checked_maps=len(selected),
                          issues=[issue for item in selected for issue in item['issues']])
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"Проверено карт: {report['checked_maps']}. Покрытие относится только к объявленным файлам.")
            for item in report['features']:
                print(f"{item['feature'] or item['map']}: смысловая проверка {item['semantic_review']}; готовность {item['ready']}")
                for key, counts in item.get('coverage', {}).items():
                    print(f'  {key}: ' + ', '.join(f'{name}={count}' for name, count in counts.items()))
            for item in report['issues']:
                print(Finding(item['severity'], item['code'], root / item['map'], item['message']).render(root))
        failed = any(item['severity'] == 'error' for item in report['issues'])
        if args.require_reviewed:
            failed |= not report['features'] or not all(item['ready'] for item in report['features'])
        return 1 if failed else 0
    except (WikiError, OSError, UnicodeError) as error:
        print('Ошибка: ' + str(error), file=sys.stderr)
        return 2
