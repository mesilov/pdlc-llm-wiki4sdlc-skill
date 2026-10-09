"""Parse OKF concept envelopes; keep conformance distinct from raw policy."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from _core import Finding, WikiError, WINDOWS_ABSOLUTE_RE, is_within

OKF_VERSION = '0.2'
OKF_COMMIT = 'ad30107c31c06aec8a7d5636e0d1058118604e6f'
ACTOR = re.compile(r'(?:human:[^\s:]+|process:[^\s:]+|[^\s/]+/[^\s/]+)\Z')
TIMESTAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z')
RAW_TYPES = {'sources': 'Source material', 'research': 'Research study'}


def yaml_module():
    try:
        import yaml
    except ImportError as error:
        raise WikiError('Нужен PyYAML 6.0.3: python3 -m pip install -r bin/wiki/requirements.txt') from error
    return yaml


def parse_yaml(text):
    yaml = yaml_module()

    class UniqueLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            seen = set()
            for key, _value in node.value:
                name = '<<' if key.tag == 'tag:yaml.org,2002:merge' else self.construct_object(key, deep=deep)
                try:
                    if name in seen:
                        raise yaml.constructor.ConstructorError(
                            None, None, 'Повтор YAML mapping key', key.start_mark)
                    seen.add(name)
                except TypeError:
                    raise yaml.constructor.ConstructorError(
                        None, None, 'YAML mapping key должен быть скаляром', key.start_mark) from None
            return super().construct_mapping(node, deep=deep)

    return yaml.load(text, Loader=UniqueLoader)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def timestamp(value):
    if isinstance(value, datetime):
        return value.tzinfo is not None and value.utcoffset() is not None
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def concept_findings(path: Path, root: Path, category: str, *, okf_only=False):
    findings = []

    def error(code, message, line=1):
        findings.append(Finding('error', code, path, message, line))

    def policy(code, message):
        findings.append(Finding('warning' if okf_only else 'error',
                                code.replace('E_RAW_', 'W_OKF_') if okf_only else code,
                                path, message, 2))

    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        error('E_RAW_READ', f'Нельзя прочитать UTF-8 README.md: {type(exc).__name__}')
        return findings
    lines = text.splitlines()
    if not lines or lines[0] != '---':
        error('E_OKF_FRONTMATTER', 'Нужен YAML frontmatter между строками --- в начале файла')
        return findings
    end = next((number for number, line in enumerate(lines[1:], 1) if line == '---'), None)
    if end is None:
        error('E_OKF_FRONTMATTER', 'Не найден конец YAML frontmatter')
        return findings
    yaml = yaml_module()
    try:
        metadata = parse_yaml('\n'.join(lines[1:end]))
    except (yaml.YAMLError, ValueError, TypeError, AttributeError, IndexError, OverflowError, RecursionError) as exc:
        mark = getattr(exc, 'problem_mark', None)
        error('E_OKF_YAML', 'Невалидный или небезопасный YAML: ' +
              str(getattr(exc, 'problem', type(exc).__name__)), mark.line + 2 if mark else 2)
        return findings
    if not isinstance(metadata, dict):
        error('E_OKF_YAML', 'Frontmatter должен быть YAML mapping')
        return findings
    if not nonempty(metadata.get('type')):
        error('E_OKF_TYPE', 'type должен быть непустой строкой', 2)
    if not okf_only:
        expected = RAW_TYPES.get(category)
        if expected and nonempty(metadata.get('type')) and metadata['type'] != expected:
            policy('E_RAW_TYPE', f'Для категории {category} дефолтный raw type: {expected}')
        for key in ('title', 'description'):
            if not nonempty(metadata.get(key)):
                policy('E_RAW_FIELD', f'{key} должен быть непустой строкой')
        if not '\n'.join(lines[end + 1:]).strip():
            policy('E_RAW_BODY', 'Нужен Markdown body с происхождением, контекстом, составом и ограничениями')
        if 'sources' not in metadata:
            policy('E_RAW_FIELD', 'Нужен sources: список оснований; [] требует пояснения агентом')
    for key in ('title', 'description', 'resource'):
        if key in metadata and not nonempty(metadata[key]) and (okf_only or key == 'resource'):
            policy('E_RAW_FIELD', f'{key} должен быть непустой строкой')
    if 'tags' in metadata and (not isinstance(metadata['tags'], list) or
                              not all(nonempty(tag) for tag in metadata['tags'])):
        policy('E_RAW_FIELD', 'tags должен быть списком непустых строк')
    if 'status' in metadata and metadata['status'] not in ('draft', 'stable', 'deprecated'):
        policy('E_RAW_FIELD', 'status документа OKF: draft/stable/deprecated; это не статус решения')
    if 'stale_after' in metadata and not timestamp(metadata['stale_after']):
        policy('E_RAW_TIMESTAMP', 'stale_after должен быть ISO 8601 datetime с UTC offset')

    def actor_event(value, label, require_at):
        if not isinstance(value, dict):
            policy('E_RAW_FIELD', f'{label} должен быть mapping с by и at')
            return
        if not isinstance(value.get('by'), str) or not ACTOR.fullmatch(value['by']):
            policy('E_RAW_FIELD', f'{label}.by: human:<id>, process:<id> или <producer>/<version>')
        if (require_at or 'at' in value) and not timestamp(value.get('at')):
            policy('E_RAW_TIMESTAMP', f'{label}.at должен быть ISO 8601 datetime с UTC offset')

    if 'generated' in metadata:
        actor_event(metadata['generated'], 'generated', False)
    if 'verified' in metadata:
        events = metadata['verified']
        if isinstance(events, dict):
            events = [events]
        if not isinstance(events, list):
            policy('E_RAW_FIELD', 'verified должен быть mapping или списком событий')
        else:
            for number, event in enumerate(events):
                actor_event(event, f'verified[{number}]', True)
    sources = metadata.get('sources', [])
    if not isinstance(sources, list):
        policy('E_RAW_FIELD', 'sources должен быть списком')
    else:
        ids = set()
        for number, source in enumerate(sources):
            label = f'sources[{number}]'
            if not isinstance(source, dict):
                policy('E_RAW_FIELD', f'{label} должен быть mapping')
                continue
            identifier = source.get('id')
            if not okf_only or identifier is not None:
                if not nonempty(identifier) or identifier in ids:
                    policy('E_RAW_SOURCE_ID', f'{label}.id должен быть непустым уникальным ID')
                else:
                    ids.add(identifier)
            resource = source.get('resource')
            if not nonempty(resource):
                policy('E_RAW_FIELD', f'{label}.resource должен быть непустой строкой')
            elif not okf_only:
                resource_findings(path, root, resource, findings)
            if 'last_modified' in source and not timestamp(source['last_modified']):
                policy('E_RAW_TIMESTAMP', f'{label}.last_modified должен быть ISO 8601 datetime с UTC offset')
            if 'usage_count' in source and (type(source['usage_count']) is not int or source['usage_count'] < 0):
                policy('E_RAW_FIELD', f'{label}.usage_count должен быть неотрицательным integer')
            for key in ('title', 'author'):
                if key in source and not nonempty(source[key]):
                    policy('E_RAW_FIELD', f'{label}.{key} должен быть непустой строкой')
            if 'usage_window' in source:
                window_findings(source['usage_window'], label + '.usage_window', policy)
    if 'usage_window' in metadata:
        window_findings(metadata['usage_window'], 'usage_window', policy)
    if metadata.get('type') == 'Attested Computation':
        if not nonempty(metadata.get('runtime')):
            policy('E_RAW_FIELD', 'Attested Computation требует runtime')
        findings.append(Finding('warning', 'W_OKF_ATTESTATION', path,
                                'Выполнение вычисления и полная проверка computation/executor/attester не входят в root lint'))
    return findings


def window_findings(value, label, policy):
    if not isinstance(value, dict):
        policy('E_RAW_FIELD', f'{label} должен быть mapping с from и to')
        return
    for key in ('from', 'to'):
        if not timestamp(value.get(key)):
            policy('E_RAW_TIMESTAMP', f'{label}.{key} должен быть ISO 8601 datetime с UTC offset')


def resource_findings(path, root, resource, findings):
    def error(message):
        findings.append(Finding('error', 'E_RAW_RESOURCE', path, message, 2))

    try:
        address = urlsplit(resource)
        if WINDOWS_ABSOLUTE_RE.match(resource) or resource.startswith('/') or address.scheme == 'file':
            error('Локальные resource должны быть относительными адресами внутри checkout')
            return
        if address.scheme:
            return  # No network requests: a URI is not evidence of accessibility.
        target = (path.parent / unquote(address.path)).resolve()
        if not is_within(target, root.resolve()):
            error('resource выходит за пределы checkout, включая symlink')
        elif not target.exists():
            if any(character.isspace() for character in resource) and not resource.startswith(('./', '../')):
                findings.append(Finding('warning', 'W_RAW_SOURCE_SCOPE', path,
                                        'resource может описывать область вместо доступного артефакта; проверьте происхождение', 2))
            else:
                error('Не найдена локальная цель sources.resource')
    except (OSError, RuntimeError, ValueError):
        error('Нельзя разрешить sources.resource внутри checkout')
