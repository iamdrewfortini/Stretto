# Figures

Every figure is generated from the code and recorded data by `python scripts/make_figures.py` and checked for staleness by `--check` [C:figures-current]. None is hand-drawn.

| Figure | What it shows | Backed by |
|---|---|---|
| ![](figures/architecture.svg) | **The system.** Two tool sets and the mirror; arrows are the real package dependencies | [C:release-gates] |
| ![](figures/wf13d-address.svg) | **WF-13D.** One 18-bit word; the ask order for a worked address, step by step | [C:wf13d-recorded-tool] |
| ![](figures/distance-from-coherence.svg) | **The problem as a number.** Distance from coherence for the recorded cluster; unmeasured axes drawn as empty | [C:distance-lower-bound] [C:intent-dominates-D] |
| ![](figures/ant-highway.svg) | **Escape direction.** Langton's ant at the moment it locks into its highway | [C:ant-empty-grid] |
| ![](figures/ant-steps.svg) | **How long locking takes.** Steps needed by each address-seeded cell | [C:ant-seeded-cells] |
| ![](figures/tesseract.svg) | **Four-axis state.** The 4-cube of coherence states, coloured by how many axes are coherent | [C:tesseract-counts] |
| ![](figures/attention-mirror.svg) | **The mirror.** Human and machine attention over the 13 loop dimensions, and where they disagree | [C:mirror-properties] |
| ![](figures/handoff-graph.svg) | **Handoff.** A procedure as a graph; a deleted step and the gap the checker reports | [C:handoff-removal-flagged] |
| ![](figures/step-scores.svg) | **Step scores.** One extraction scored at different matcher thresholds; agreement between the two signals as effects get noisier | [C:step-score-threshold-swing] [C:step-signal-agreement] [C:step-score-booster-safe] |
| ![](figures/privacy-flow.svg) | **Privacy.** Every arrow passes a gate; each gate has a test | [C:consent-default-deny] [C:rollup-privacy] |
| ![](figures/gossip.svg) | **Cache to cache.** Rounds for all cells to hold identical state, versus number of cells | [C:gossip-converges-fast] |
| ![](figures/speed.svg) | **Native speed.** Python versus Rust on the same machine | [C:rust-faster] |
| ![](figures/pipeline.svg) | **Release.** From a clean commit to a verified, rollback-safe install | [C:installer-round-trip] |
