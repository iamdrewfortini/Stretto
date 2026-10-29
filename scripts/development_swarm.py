#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Review-only development flow through the existing Bifrost gateway; no code is applied."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(p) for p in sorted((ROOT / 'packages').glob('*/src'))]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('flow', type=Path)
    parser.add_argument('--rubric', required=True, type=Path)
    parser.add_argument('--mode', choices=('plan', 'offline-dry-run', 'live'), default='plan')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--dry-run-evidence', type=Path)
    parser.add_argument('--owner-authorization', default='')
    parser.add_argument('--gateway-contract-evidence', type=Path)
    parser.add_argument('--circuit-evidence', type=Path)
    args = parser.parse_args(argv)
    from cells.development import DevelopmentTask, ExecutionPolicy, DevelopmentSwarm
    from metarouter.gateway import GatewayClient, GatewayConfig, LiveGate
    from metarouter.router import Endpoint, MetaRouter
    if args.flow.stat().st_size > 8388608:
        raise ValueError('flow file exceeds resource bound')
    raw = args.flow.read_bytes()
    flow_hash = hashlib.sha256(raw).hexdigest()
    flow = json.loads(raw)
    rubric_hash = digest(args.rubric)
    if type(flow.get('allow_credits', False)) is not bool:
        raise ValueError('allow_credits requires an explicit boolean')
    if flow.get('rubric_sha256') != rubric_hash:
        raise ValueError('flow must acknowledge the current rubric hash')
    tasks = [DevelopmentTask(**t) for t in flow['tasks']]
    policy = ExecutionPolicy(rubric_sha256=rubric_hash)
    swarm = DevelopmentSwarm(tasks, policy, max_concurrency=flow.get('max_concurrency', 1))
    base = {'mode': args.mode, 'flow_sha256': flow_hash, 'rubric_sha256': rubric_hash,
            'evidence_scope': 'development artifacts only; no product verification or automatic application'}
    if args.mode == 'plan':
        print(json.dumps(dict(base, status='PLANNED', tasks=[t.id for t in tasks]), indent=2))
        return 0
    if args.output is None or args.output.exists():
        raise ValueError('execution requires a new --output directory')
    client = None
    router = None
    token_lock = threading.Lock()
    reserved = 0
    per_call = flow.get('max_tokens_per_call', 512)
    total_limit = flow.get('max_total_completion_tokens', 4096)
    if type(per_call) is not int or per_call <= 0 or type(total_limit) is not int or total_limit < per_call:
        raise ValueError('invalid completion token reservation limits')
    if args.mode == 'live':
        if args.dry_run_evidence is None:
            raise ValueError('live execution requires checked dry-run evidence')
        proof = json.loads(args.dry_run_evidence.read_text())
        if not (proof.get('mode') == 'offline-dry-run' and proof.get('flow_contract_passed') is True
                and proof.get('flow_sha256') == flow_hash and proof.get('rubric_sha256') == rubric_hash):
            raise ValueError('dry-run proof does not match this flow and rubric')
        if args.circuit_evidence is None:
            raise ValueError('recorded-data circuit proof remains required; fixtures do not satisfy it')
        circuit = json.loads(args.circuit_evidence.read_text())
        if not (circuit.get('status') == 'VERIFIED'
                and circuit.get('scope') == 'handoff-recorded-phase1'
                and circuit.get('rubric_sha256') == rubric_hash
                and circuit.get('evidence')
                and circuit.get('owner_ratification')):
            raise ValueError('recorded-data circuit evidence is incomplete')
        gate = LiveGate(dry_run_proven=True, owner_authorized=bool(args.owner_authorization.strip()),
                        dry_run_evidence=str(args.circuit_evidence), owner_evidence=args.owner_authorization)
        gate.require()
        cfg = flow['gateway']
        if args.gateway_contract_evidence is None:
            raise ValueError('live execution requires gateway contract evidence')
        contract = json.loads(args.gateway_contract_evidence.read_text())
        if not (contract.get('base_url') == cfg['base_url']
                and contract.get('status') == 'VERIFIED'
                and contract.get('evidence')):
            raise ValueError('gateway contract evidence does not match configured origin')
        if cfg.get('allow_loopback_http'):
            raise ValueError('live development CLI requires HTTPS gateway')
        policy = ExecutionPolicy(rubric_sha256=rubric_hash, mode='meta-api', approved_gates=(
            'circuit-dry-run-proven', 'owner-approved-meta-calls', 'meta-gateway-contract-verified'))
        swarm = DevelopmentSwarm(tasks, policy, max_concurrency=flow.get('max_concurrency', 1))
        client = GatewayClient(GatewayConfig(**cfg), gate=gate)
        eps = [Endpoint(**e) for e in flow.get('endpoints', [])]
        router = MetaRouter(eps, allow_credits=flow.get('allow_credits', False))

    def run(task, dependencies, attempt):
        nonlocal reserved
        if args.mode == 'offline-dry-run':
            output = flow.get('dry_run_outputs', {}).get(task.id)
            if output is None:
                raise ValueError('missing explicit offline fixture for task ' + task.id)
            return output
        with token_lock:
            if reserved + per_call > total_limit:
                raise ValueError('completion token reservation budget exhausted')
            reserved += per_call
        eligible = router.order(task.role, task=task.id)
        if not eligible:
            raise ValueError('NO_SIGNAL: no eligible Meta gateway endpoint')
        prompt = {'instruction': task.instruction, 'owned_paths': task.owned_paths, 'dependencies': dict(dependencies),
                  'required_output': {'rubric_sha256': rubric_hash, 'artifacts': {'owned/path': 'proposed text'},
                                      'evidence': ['sources and limitations; never claim unrun tests passed']}}
        response = client.complete(eligible[0].model, [
            {'role': 'system', 'content': args.rubric.read_text() + '\nReturn JSON only. Produce reviewable development artifacts; do not execute commands or claim model consensus.'},
            {'role': 'user', 'content': json.dumps(prompt)}], role=task.role, max_tokens=per_call)
        output = json.loads(response['content'])
        output['transport_evidence'] = {'model': response.get('model'), 'usage': response.get('usage'),
                                        'status': 'UNVERIFIED_PROPOSAL', 'attempt': attempt}
        return output

    report = swarm.execute(run, lambda task, output: bool(output.get('artifacts')))
    # The engine's checks prove task contract conformance, not generated code correctness.
    passed = report.get('status') == 'CHECKED'
    result = dict(base, flow_contract_passed=passed, completion_tokens_reserved=reserved, report=report)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        # Do not print upstream payloads, env vars or exception text that may contain credentials.
        print(json.dumps({'status': 'BLOCKED', 'error_type': type(exc).__name__, 'why': 'flow validation or execution failed; no artifacts applied'}))
        sys.exit(2)
