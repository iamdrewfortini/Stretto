# SPDX-License-Identifier: Apache-2.0
import unittest
from cells.acceptance import artifact_checks


class Acceptance(unittest.TestCase):
    def test_python_is_parsed_and_never_executed(self):
        out = {'artifacts': {'a.py': 'raise RuntimeError("would fail if executed")\n'}}
        self.assertTrue(artifact_checks(out, {'a.py': [{'kind': 'python-syntax'}]})['passed'])
        out['artifacts']['a.py'] = 'def broken('
        self.assertFalse(artifact_checks(out, {'a.py': [{'kind': 'python-syntax'}]})['passed'])

    def test_json_keys_duplicates_nonfinite_and_wrong_type(self):
        rule = {'a.json': [{'kind': 'json-object', 'required_keys': ['steps']}]}
        for text, expected in (('{"steps":[]}', True), ('{}', False), ('[]', False),
                               ('{"steps":1,"steps":2}', False), ('{"steps":NaN}', False)):
            self.assertEqual(artifact_checks({'artifacts': {'a.json': text}}, rule)['passed'], expected)

    def test_rules_and_artifacts_must_match_and_unknown_rules_fail(self):
        for spec in ({}, {'a': []}, {'a': [{'kind': 'run-shell'}]}, {'a': [{'kind': 'nonempty', 'extra': True}]}):
            self.assertFalse(artifact_checks({'artifacts': {'a': 'text'}}, spec)['passed'])
        self.assertFalse(artifact_checks({'artifacts': {'a': ' '}}, {'a': [{'kind': 'nonempty'}]})['passed'])

    def test_contains_requires_exact_nonempty_literal(self):
        out = {'artifacts': {'a': 'OFFLINE FIXTURE'}}
        self.assertTrue(artifact_checks(out, {'a': [{'kind': 'contains', 'text': 'OFFLINE FIXTURE'}]})['passed'])
        for term in ('', 'LIVE VERIFIED'):
            self.assertFalse(artifact_checks(out, {'a': [{'kind': 'contains', 'text': term}]})['passed'])
