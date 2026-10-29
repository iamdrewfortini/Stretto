# SPDX-License-Identifier: Apache-2.0
"""CLI acceptance: offline execution, provenance binding and live default refusal."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DevelopmentFlow(unittest.TestCase):
    def invoke(self, flow, rubric, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/development_swarm.py'), str(flow),
                               '--rubric', str(rubric), *map(str, args)], capture_output=True, text=True)

    def fixture(self, root):
        rubric = root / 'rubric.md'
        rubric.write_text('A test rubric, not the product evaluation.\n')
        value = json.loads((ROOT / 'examples/development-swarm/feature-flow.json').read_text())
        h = hashlib.sha256(rubric.read_bytes()).hexdigest()
        value['rubric_sha256'] = h
        for task in value['tasks']:
            task['rubric_sha256'] = h
            value['dry_run_outputs'][task['id']]['rubric_sha256'] = h
        flow = root / 'flow.json'
        flow.write_text(json.dumps(value))
        return flow, rubric, value

    def test_plan_and_offline_flow_never_apply_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            flow, rubric, _ = self.fixture(root)
            plan = self.invoke(flow, rubric)
            self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
            self.assertEqual(json.loads(plan.stdout)['status'], 'PLANNED')
            run = self.invoke(flow, rubric, '--mode', 'offline-dry-run', '--output', root / 'result')
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            report = json.loads((root / 'result/report.json').read_text())
            self.assertTrue(report['flow_contract_passed'])
            self.assertEqual(report['mode'], 'offline-dry-run')
            self.assertFalse((root / 'proposals').exists())

    def test_changed_rubric_refuses_before_execution(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            flow, rubric, _ = self.fixture(root)
            rubric.write_text('changed authority')
            run = self.invoke(flow, rubric, '--mode', 'offline-dry-run', '--output', root / 'result')
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse((root / 'result').exists())

    def test_live_without_proof_or_owner_approval_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            flow, rubric, _ = self.fixture(root)
            run = self.invoke(flow, rubric, '--mode', 'live', '--output', root / 'result')
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse((root / 'result').exists())

    def test_fixture_check_failure_cannot_become_dry_run_proof(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            flow, rubric, value = self.fixture(root)
            value['dry_run_outputs']['plan']['artifacts'] = {}
            flow.write_text(json.dumps(value))
            run = self.invoke(flow, rubric, '--mode', 'offline-dry-run', '--output', root / 'result')
            self.assertNotEqual(run.returncode, 0)
            if (root / 'result/report.json').exists():
                self.assertFalse(json.loads((root / 'result/report.json').read_text())['flow_contract_passed'])

    def test_fixture_report_alone_never_closes_recorded_data_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            flow, rubric, _ = self.fixture(root)
            offline = self.invoke(flow, rubric, '--mode', 'offline-dry-run', '--output', root / 'offline')
            self.assertEqual(offline.returncode, 0, offline.stdout + offline.stderr)
            run = self.invoke(flow, rubric, '--mode', 'live', '--output', root / 'live',
                              '--dry-run-evidence', root / 'offline/report.json',
                              '--owner-authorization', 'test declaration only')
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse((root / 'live').exists())
