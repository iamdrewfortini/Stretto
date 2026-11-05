# SPDX-License-Identifier: Apache-2.0
# Convenience targets. Heavy targets (rust, package) should run on a build host, not a workstation.
PY ?= python3
ROOT := $(CURDIR)
export PYTHONPATH := $(shell ls -d $(ROOT)/packages/*/src | tr '\n' :)
ENV_FILE ?= $(HOME)/.config/humanflow/runtime.env

.PHONY: test check claims figures package rust setup env-check why gateway sensors-probe sensors-grant demo install verify-install

# --- community development ---
test:
	$(PY) scripts/run_all_tests.py
check:
	$(PY) scripts/release_check.py && $(PY) scripts/docs_lint.py && $(PY) scripts/make_figures.py --check
claims:
	$(PY) scripts/verify_claims.py --require-all --write
figures:
	$(PY) scripts/make_figures.py
rust:
	cd crates && cargo test --release --locked
package:
	$(PY) scripts/package.py --out dist

# --- secure environments (ENV-STANDARD-01) ---
setup: ## create the real env OUTSIDE the worktree (0600), from the public example
	@mkdir -p "$(dir $(ENV_FILE))"
	@if [ -f "$(ENV_FILE)" ]; then echo "exists: $(ENV_FILE) (left untouched)"; \
	else $(PY) -c "import os,sys; src=open('.env.example').readlines(); out=[l.split(' #',1)[0].rstrip() for l in src if l.strip() and not l.startswith('#') and '=' in l]; fd=os.open('$(ENV_FILE)', os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600); os.write(fd, ('\n'.join(out)+'\n').encode()); os.close(fd)"; \
	chmod 600 "$(ENV_FILE)"; echo "created $(ENV_FILE) — set MODEL_API_KEY there (never in the repo)"; fi
env-check: ## prove the env is complete, private, local-only (never prints a secret)
	HUMANFLOW_ENV="$(ENV_FILE)" $(PY) scripts/env_check.py
why: ## the installer gate against The Why
	$(PY) scripts/why_check.py

# --- live sockets ---
gateway: ## real runtime gateway on 127.0.0.1:8787 (requires MODEL_API_KEY in $(ENV_FILE))
	HUMANFLOW_ENV="$(ENV_FILE)" scripts/with_env.sh $(PY) -m runtime.gateway
sensors-probe:
	$(PY) -m sensors probe
sensors-grant:
	$(PY) -m sensors grant window idle --ttl 8h
demo: sensors-probe sensors-grant ## sensors -> gateway (run `make gateway` in another terminal first)
	$(PY) -m sensors run --gateway http://127.0.0.1:8787

# --- production installer ---
install: ## full installer (verifies bundle + Why, then installs for this user)
	installer/install.sh --user
verify-install: ## verify a bundle without installing
	installer/install.sh --user --verify-only
