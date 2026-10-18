# Demo pack

Ready-made results to show without running anything. Produced by the FULL run (`python -m paper.make`, 570 s on 2 cores): many classrooms
per point, 95% bootstrap confidence intervals. **All radio, phone and human parameters are simulated with assumed values** (no real-phone data yet).

* `results/KEY_NUMBERS.md` - the headline numbers on one page.
* `results/summary.md` - every table of E01-E14.
* `results/figures/` - charts (PNG for slides, PDF for the paper). Best for the professor: `e09_baselines`, `e03_attacks`, `e01_accuracy`, `e04_platforms`, `e10_backbench`.
* `results/tables/` - the same tables as Markdown and LaTeX.
* `results/results/` - raw numbers (JSON) and the per-experiment hashes.

Regenerate: `cd backend && python -m paper.make && python -m paper.key_numbers`. What to say about it: `../paper-material/PAPER_MATERIAL.md`. How to run everything: `../USAGE.md`.
