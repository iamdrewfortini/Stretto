# SPDX-License-Identifier: Apache-2.0
"""Named static artifact checks. No generated code is executed by these checks."""
import ast
import json


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def validate_check_spec(specification):
    """Validate named deterministic checks before a plan is reported as valid."""
    if not isinstance(specification, dict) or not specification:
        raise ValueError('nonempty artifact acceptance mapping required')
    for path, rules in specification.items():
        if not isinstance(path, str) or not path or not isinstance(rules, list) or not rules:
            raise ValueError('artifact paths and nonempty check rules required')
        for rule in rules:
            if not isinstance(rule, dict):
                raise ValueError('check rule must be an object')
            kind = rule.get('kind')
            if kind in ('python-syntax', 'nonempty') and set(rule) == {'kind'}:
                continue
            if kind == 'contains' and set(rule) == {'kind', 'text'} and isinstance(rule['text'], str) and rule['text']:
                continue
            if kind == 'json-object' and set(rule) <= {'kind', 'required_keys'}:
                keys = rule.get('required_keys', [])
                if isinstance(keys, list) and all(isinstance(k, str) for k in keys):
                    continue
            raise ValueError('unknown or malformed static acceptance rule')


def artifact_checks(output, specification):
    """Return static check evidence; success does not establish feature correctness."""
    artifacts = output.get('artifacts') if isinstance(output, dict) else None
    if not isinstance(artifacts, dict) or not artifacts or not isinstance(specification, dict):
        return {'passed': False, 'scope': 'static artifact checks only', 'checks': []}
    checks = []
    if set(artifacts) != set(specification):
        return {'passed': False, 'scope': 'static artifact checks only', 'checks': [
            {'check': 'artifact-set', 'passed': False}]}
    for path in sorted(artifacts):
        text = artifacts[path]
        rules = specification[path]
        if not isinstance(text, str) or not isinstance(rules, list) or not rules:
            checks.append({'artifact': path, 'check': 'named-rules-required', 'passed': False})
            continue
        for rule in rules:
            kind = rule.get('kind') if isinstance(rule, dict) else None
            passed = False
            try:
                if kind == 'python-syntax' and set(rule) == {'kind'}:
                    ast.parse(text, filename=path)
                    passed = True
                elif kind == 'json-object' and set(rule) <= {'kind', 'required_keys'}:
                    keys = rule.get('required_keys', [])
                    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                        raise ValueError('invalid JSON check')
                    data = json.loads(text, object_pairs_hook=_object,
                                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite')))
                    passed = isinstance(data, dict) and set(keys) <= set(data)
                elif kind == 'contains' and set(rule) == {'kind', 'text'}:
                    passed = isinstance(rule['text'], str) and bool(rule['text']) and rule['text'] in text
                elif kind == 'nonempty' and set(rule) == {'kind'}:
                    passed = bool(text.strip())
            except (ValueError, SyntaxError, TypeError, RecursionError):
                passed = False
            checks.append({'artifact': path, 'check': kind if isinstance(kind, str) else 'invalid-rule',
                           'passed': passed})
    return {'passed': bool(checks) and all(c['passed'] for c in checks),
            'scope': 'static artifact checks only; not execution or product verification', 'checks': checks}
