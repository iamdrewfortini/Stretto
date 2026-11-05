#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reproducible offline cost-floor simulations; no credentials or network."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(p) for p in sorted((ROOT / 'packages').glob('*/src'))]
from metarouter.development_cost import optimize_policy, simulate_policy


def run_simulations():
    def candidate(name, model, cost, probability):
        return dict(id=name, model=model, role='coder', cost=cost, success_probability=probability)
    scenarios = [
        ('cheap-then-frontier', [candidate('economy', 'muse-wonder-1.0', 1, .75),
                                 candidate('frontier', 'muse-spark-1.3', 8, .99)], .95),
        ('frontier-is-cheaper-after-failures', [candidate('economy', 'muse-wonder-1.0', 1, .05),
                                              candidate('frontier', 'muse-spark-1.3', 8, .99)], .95),
        ('cheap-sufficient', [candidate('economy', 'muse-wonder-1.0', 1, .96),
                              candidate('frontier', 'muse-spark-1.3', 8, .99)], .95),
        ('infeasible-refuses', [candidate('economy', 'muse-wonder-1.0', 1, .2),
                               candidate('frontier', 'muse-spark-1.3', 8, .3)], .99),
    ]
    results = []
    for name, candidates, target in scenarios:
        optimization = optimize_policy(candidates, target)
        if name == 'infeasible-refuses':
            passed = optimization['status'] == 'NO_SIGNAL'
            simulations = []
        else:
            simulations = [simulate_policy(optimization, trials=10000, seed=seed) for seed in range(8)]
            passed = optimization['status'] == 'OK' and all(s['status'] == 'PASS' for s in simulations)
        results.append(dict(scenario=name, passed=passed, optimization=optimization, simulations=simulations))
    return dict(status='PASS' if all(r['passed'] for r in results) else 'MISS',
                scope='seeded synthetic simulation only; no live API or measured billing',
                objective='minimum expected declared cost satisfying supplied success floor, within finite attempt set',
                scenarios=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error('output already exists; preserve previous evidence')
    result = run_simulations()
    text = json.dumps(result, indent=2) + '\n'
    if args.output is not None:
        args.output.write_text(text)
    else:
        print(text, end='')
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
