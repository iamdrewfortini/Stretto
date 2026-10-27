# Third-party software

Everything in this repository is original except the items below. `scripts/release_check.py` fails the build if a runtime dependency or an external Rust crate appears that is not listed here.

| Component | Where it is used | License | How it is included |
|---|---|---|---|
| `cryptography` (Python) | optional: Ed25519 multi-signature in `harness.signing` | Apache-2.0 OR BSD-3-Clause | not bundled; installed by the user if signing is wanted (`metacoh-harness[signing]`) |
| Rust standard library | statically linked into `libwf13d_core` and `libant` (shared and static) | MIT OR Apache-2.0 | compiled into the native artifacts; its notice is carried by this file |
| Python standard library | all Python packages | PSF-2.0 | not redistributed |
| Apache License 2.0 text | `LICENSE` | Apache-2.0 | unmodified standard text |

Rust crates from crates.io: **none** (`crates/Cargo.lock` lists only this project's own crates).

Models: Meta models are reached over an API or run from weights the user obtains under their own license; no weights, datasets or model outputs are included.

Algorithms implemented from public definitions (no code copied): Langton's ant, ant-colony optimization (Dorigo), Erlang C queueing, Jain's fairness index, Jensen-Shannon divergence, the Hedge (exponential weights) algorithm, Holt-Winters smoothing, the Johnson-Lindenstrauss bound, Benjamini-Hochberg, CUSUM, Laplace-noise differential privacy, BM25.
