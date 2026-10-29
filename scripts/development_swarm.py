#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Review-only development flow through the existing Bifrost gateway; no code is applied."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading

STAGE = 'startup'
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(p) for p in sorted((ROOT / 'packages').glob('*/src'))]


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    if not isinstance(value, dict):
        raise ValueError('JSON document must be an object')
    return value


def main(argv=None):
    global STAGE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('flow', type=Path)
    parser.add_argument('--rubric', required=True, type=Path)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--mode', choices=('plan', 'offline-dry-run', 'live'), default='plan')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--dry-run-evidence', type=Path)
    parser.add_argument('--owner-authorization', default='')
    parser.add_argument('--gateway-contract-evidence', type=Path)
    parser.add_argument('--circuit-evidence', type=Path)
    args = parser.parse_args(argv)
    from cells.development import DevelopmentTask, ExecutionPolicy, DevelopmentSwarm
    from cells.acceptance import artifact_checks, validate_check_spec
    from cells.context import load_source_context
    from metarouter.gateway import GatewayClient, GatewayConfig, LiveGate, GatewayError
    from metarouter.development_cost import optimize_policy
    from metarouter.router import Endpoint, MetaRouter
    STAGE = 'flow-and-rubric-validation'
    if args.flow.stat().st_size > 8388608:
        raise ValueError('flow file exceeds resource bound')
    raw = args.flow.read_bytes()
    flow_hash = hashlib.sha256(raw).hexdigest()
    flow = strict_json(raw)
    if args.rubric.stat().st_size > 1048576:
        raise ValueError('rubric exceeds resource bound')
    rubric_bytes = args.rubric.read_bytes()
    rubric_text = rubric_bytes.decode('utf-8')
    rubric_hash = hashlib.sha256(rubric_bytes).hexdigest()
    if type(flow.get('allow_credits', False)) is not bool:
        raise ValueError('allow_credits requires an explicit boolean')
    if flow.get('rubric_sha256') != rubric_hash:
        raise ValueError('flow must acknowledge the current rubric hash')
    if not isinstance(flow.get('feature_request'), str) or not flow['feature_request'].strip():
        raise ValueError('feature request is required')
    criteria = flow.get('acceptance_criteria')
    if not isinstance(criteria, list) or not criteria or not all(isinstance(x, str) and x.strip() for x in criteria):
        raise ValueError('feature acceptance criteria are required')
    STAGE = 'source-context-validation'
    context = load_source_context(args.source_root.absolute(), flow.get('source_files', []))
    tasks = [DevelopmentTask(**t) for t in flow['tasks']]
    acceptance = flow.get('acceptance', {})
    if not isinstance(acceptance, dict) or set(acceptance) != {t.id for t in tasks}:
        raise ValueError('each task requires named artifact acceptance checks')
    STAGE = 'task-and-acceptance-validation'
    for task in tasks:
        validate_check_spec(acceptance[task.id])
    policy = ExecutionPolicy(rubric_sha256=rubric_hash)
    swarm = DevelopmentSwarm(tasks, policy, max_concurrency=flow.get('max_concurrency', 1))
    base = {'mode': args.mode, 'flow_sha256': flow_hash, 'rubric_sha256': rubric_hash,
            'source_context_sha256': context['sha256'],
            'evidence_scope': 'development artifacts only; no product verification or automatic application'}
    per_call = flow.get('max_tokens_per_call', 512)
    total_limit = flow.get('max_total_completion_tokens', 4096)
    if type(per_call) is not int or per_call <= 0 or type(total_limit) is not int or total_limit < per_call:
        raise ValueError('invalid completion token reservation limits')
    GatewayConfig(**flow['gateway'])
    routing_router = MetaRouter([Endpoint(**e) for e in flow.get('endpoints', [])], allow_credits=flow.get('allow_credits', False))
    estimates = flow.get('success_probability_estimates', {})
    if not isinstance(estimates, dict):
        raise ValueError('success estimates must be an explicit mapping')
    routing_plans = {}
    for task in tasks:
        candidates = [dict(id=e.name, model=e.model, role=task.role, cost=e.cost, success_probability=estimates[e.name])
                      for e in routing_router.eligible(task.role) if e.name in estimates]
        routing_plans[task.id] = optimize_policy(candidates, flow.get('required_success_probability', 0.95),
                                                max_attempts=task.max_attempts) if candidates else {
                                                    'status':'NO_SIGNAL', 'reason':'No eligible endpoints with declared success probabilities.'}
    base['routing_plans'] = routing_plans
    base['live_routing_status'] = 'CONFIGURED_UNVERIFIED' if all(p['status'] == 'OK' for p in routing_plans.values()) else 'NO_SIGNAL'
    if args.mode == 'plan':
        blocked = {key: reasons for key, reasons in swarm.preflight().items() if reasons}
        print(json.dumps(dict(base, status='BLOCKED' if blocked else 'PLANNED',
                              tasks=[t.id for t in tasks], blocked=blocked), indent=2))
        return 1 if blocked else 0
    if args.output is None or args.output.exists():
        raise ValueError('execution requires a new --output directory')
    client = None
    router = None
    token_lock = threading.Lock()
    reserved = 0
    if args.mode == 'live':
        STAGE = 'live-evidence-validation'
        if args.dry_run_evidence is None:
            raise ValueError('live execution requires checked dry-run evidence')
        proof = strict_json(args.dry_run_evidence.read_text())
        if not (proof.get('mode') == 'offline-dry-run' and proof.get('flow_contract_passed') is True
                and proof.get('flow_sha256') == flow_hash and proof.get('rubric_sha256') == rubric_hash
                and proof.get('source_context_sha256') == context['sha256']):
            raise ValueError('dry-run proof does not match this flow and rubric')
        if args.circuit_evidence is None:
            raise ValueError('recorded-data circuit proof remains required; fixtures do not satisfy it')
        circuit = strict_json(args.circuit_evidence.read_text())
        if not (circuit.get('status') == 'VERIFIED'
                and circuit.get('scope') == 'handoff-recorded-phase1'
                and circuit.get('rubric_sha256') == rubric_hash
                and isinstance(circuit.get('evidence'), str) and circuit['evidence'].strip()
                and isinstance(circuit.get('owner_ratification'), str) and circuit['owner_ratification'].strip()):
            raise ValueError('recorded-data circuit evidence is incomplete')
        gate = LiveGate(dry_run_proven=True, owner_authorized=bool(args.owner_authorization.strip()),
                        dry_run_evidence=str(args.circuit_evidence), owner_evidence=args.owner_authorization)
        gate.require()
        cfg = flow['gateway']
        if args.gateway_contract_evidence is None:
            raise ValueError('live execution requires gateway contract evidence')
        contract = strict_json(args.gateway_contract_evidence.read_text())
        if not (contract.get('base_url') == cfg['base_url']
                and contract.get('status') == 'VERIFIED'
                and isinstance(contract.get('evidence'), str) and contract['evidence'].strip()):
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
        selection = routing_plans[task.id]
        if selection['status'] != 'OK' or attempt > len(selection['policy']['attempts']):
            raise GatewayError('NO_SIGNAL: no admissible cost/reliability policy', status='NO_SIGNAL')
        selected = selection['policy']['attempts'][attempt - 1]
        selected_endpoint = next((e for e in router.eligible(task.role) if e.name == selected['id']), None)
        if selected_endpoint is None:
            raise GatewayError('NO_SIGNAL: selected endpoint is no longer eligible', status='NO_SIGNAL')
        prompt = {'feature_request': flow['feature_request'], 'acceptance_criteria': criteria,
                  'source_context': context, 'instruction': task.instruction, 'owned_paths': task.owned_paths, 'dependencies': dict(dependencies),
                  'acceptance': acceptance[task.id],
                  'required_output': {'rubric_sha256': rubric_hash, 'artifacts': {'owned/path': 'proposed text'},
                                      'evidence': ['sources and limitations; never claim unrun tests passed']}}
        response = client.complete(selected_endpoint.model, [
            {'role': 'system', 'content': rubric_text + '\nReturn JSON only. Produce reviewable development artifacts; do not execute commands or claim model consensus.'},
            {'role': 'user', 'content': json.dumps(prompt)}], role=task.role, max_tokens=per_call)
        if response.get('finish_reason') != 'stop':
            raise ValueError('incomplete or filtered generated artifact response')
        output = strict_json(response['content'])
        output['transport_evidence'] = {'model': response.get('model'), 'usage': response.get('usage'),
                                        'status': 'UNVERIFIED_PROPOSAL', 'attempt': attempt}
        return output

    acceptance_results = {}

    def check(task, output):
        result = artifact_checks(output, acceptance[task.id])
        acceptance_results[task.id] = result
        return result['passed']

    STAGE = 'task-execution'
    report = swarm.execute(run, check)
    report['acceptance_checks'] = acceptance_results
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
        print(json.dumps({'status': 'BLOCKED', 'error_type': type(exc).__name__, 'stage': STAGE, 'why': 'flow validation or execution failed; no artifacts applied'}))
        sys.exit(2)
