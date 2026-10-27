# SPDX-License-Identifier: Apache-2.0
# Convenience targets. Heavy targets (rust, package) should run on a build host, not a workstation.
.PHONY: test check claims figures package rust
test:
	python3 scripts/run_all_tests.py
check:
	python3 scripts/release_check.py && python3 scripts/docs_lint.py && python3 scripts/make_figures.py --check
claims:
	python3 scripts/verify_claims.py --require-all --write
figures:
	python3 scripts/make_figures.py
rust:
	cd crates && cargo test --release --locked
package:
	python3 scripts/package.py --out dist
