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

    def test_plan_refuses_invalid_rules_tokens_and_task_ack(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            flow, rubric, original = self.fixture(root)
            for bad in ('rules', 'tokens', 'ack', 'action', 'held-gate'):
                value = json.loads(json.dumps(original))
                if bad == 'rules': value['acceptance']['plan']['proposals/plan.md'] = [{'kind':'unsupported'}]
                if bad == 'tokens': value['max_tokens_per_call'] = -1
                if bad == 'ack': value['tasks'][0]['rubric_sha256'] = '0' * 64
                if bad == 'action': value['tasks'][0]['action'] = 'deploy'
                if bad == 'held-gate': value['tasks'][0]['required_gates'] = ['owner-held']
                flow.write_text(json.dumps(value))
                run = self.invoke(flow, rubric)
                self.assertNotEqual(run.returncode, 0, bad + run.stdout + run.stderr)

    def test_duplicate_config_keys_fail_loudly(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            flow, rubric, _ = self.fixture(root)
            flow.write_text('{"max_concurrency":1,"max_concurrency":2}')
            run = self.invoke(flow, rubric)
            self.assertEqual(run.returncode, 2)
            report = json.loads(run.stdout)
            self.assertEqual(report['status'], 'BLOCKED')
            self.assertEqual(report['stage'], 'flow-and-rubric-validation')

    def test_changed_source_refuses_before_callbacks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            flow, rubric, value = self.fixture(root)
            source = root / 'source.py'
            source.write_text('def baseline(): return True\n')
            value['source_files'] = [{'path':'source.py','sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]
            flow.write_text(json.dumps(value))
            source.write_text('changed baseline')
            run = self.invoke(flow, rubric, '--source-root', root)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(json.loads(run.stdout)['stage'], 'source-context-validation')

    def test_nonobject_json_returns_staged_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            flow, rubric, _ = self.fixture(root)
            for raw in ('[]', 'null', '42', '"value"'):
                flow.write_text(raw)
                run = self.invoke(flow, rubric)
                self.assertEqual(run.returncode, 2)
                self.assertEqual(json.loads(run.stdout)['status'], 'BLOCKED')
                self.assertNotIn('Traceback', run.stderr)

    def test_cost_plan_reaches_declared_floor_and_exposes_infeasible_routes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            flow, rubric, value = self.fixture(root)
            value['endpoints'] = [
                {'name':'economy','model':'muse-wonder-1.0','status':'live','cost':1},
                {'name':'frontier','model':'muse-spark-1.3','status':'live','cost':8}]
            value['success_probability_estimates'] = {'economy':.75,'frontier':.99}
            for task in value['tasks']: task['max_attempts'] = 2
            flow.write_text(json.dumps(value))
            run = self.invoke(flow, rubric)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            report = json.loads(run.stdout)
            self.assertEqual(report['live_routing_status'], 'CONFIGURED_UNVERIFIED')
            for policy in report['routing_plans'].values():
                self.assertEqual(policy['policy']['exact']['expected_cost'], '3')
                self.assertEqual(policy['optimality']['exact_cost_gap_to_oracle'], '0')
            value['required_success_probability'] = 1
            flow.write_text(json.dumps(value))
            run = self.invoke(flow, rubric)
            self.assertEqual(json.loads(run.stdout)['live_routing_status'], 'NO_SIGNAL')
