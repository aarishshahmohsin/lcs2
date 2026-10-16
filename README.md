# LCS2 Coding Round — step-by-step build

Each file is one stage of the assignment, in the order you build it. Every file imports the
one before it (`step3` imports `step2`, which imports `step1`) and adds only what its own task
needs: its prompt conditions, its metrics, its statistics and its analysis. Read each file's
docstring first; it explains what that step adds and what to check before moving on.

| # | File | Brief section | Adds | Model runs (per model) |
|---|---|---|---|---|
| 1 | `step1_setup.py` | §3 | Fixed config, dataset download + validation, `Runner` (model loading, generation, option-letter probabilities), revision pinning | toy check |
| 2 | `step2_baseline.py` | Part A | JSON prompt, condition registry, parsing rule, run + save raw outputs, processing, z-intervals, calibration gap, ROC AUC, plotting, hypotheses | 200 |
| 3 | `step3_hallucination.py` | B.1 | `misleading` condition, adoption + evidence-reliance fields, McNemar, paired t-test, H1 test | 60 |
| 4 | `step4_interpretability.py` | B.2 | Interp set, clean prompt: occlusion, gradient×input, deletion faithfulness test vs random and bottom-k controls (paired t-test), logit lens, evidence vs attribution | 40 |
| 5 | `step5_fairness.py` | B.3 | 6 prepended metadata conditions, flip rates vs any-metadata-line control (McNemar), explanation word overlap, paired t-tests, relevance flag | 360 |
| 6 | `step6_security.py` | B.4 | `injection` + `canary` conditions, leak-detection rule, refusal check | 120 |
| 7 | `step7_cross_dimension.py` | Part C | ROC AUC with z-intervals (H2 test), two-sample t-test, McNemar (C4) | none |
| 8 | `step8_intervention.py` | Part D | Hardened system prompt + `<untrusted_question>` delimiting, before/after on the same 60 items, costs, regressions | 240 |
| – | `extra_reasoning.py` | beyond scope | Exploratory reasoning-first format (H3, post hoc); does not replace any required run | 260 |
| 9 | `step9_report.py` | §8 | All sections in one `summary.md`, compliance checklist, run inventory, case studies | none |
| – | `selftest.py` | – | CPU-only checks of the prompt strings, parser and leak rule, then the full report on synthetic data | none |

## Running on Kaggle (fresh notebook)

Use `lcs2-assignment.ipynb` at the repository root:

1. Push this repository to GitHub. On Hugging Face, accept the licence of
   `meta-llama/Llama-3.2-3B-Instruct` and create a read token.
2. On Kaggle: **Code → New Notebook → File → Import Notebook →** `lcs2-assignment.ipynb`. [Online link](https://www.kaggle.com/code/aarishshahmohsin/lcs2-assignment)
3. Notebook settings: **Accelerator: GPU T4 x2** (one GPU is used; recent PyTorch may not support the
   P100), **Internet: On**, **Add-ons → Secrets:** `HF_TOKEN` (plus `GITHUB_TOKEN` if the repository is
   private), switched on for this notebook.
4. In the first code cell set `REPO_URL` (and `BRANCH`).
5. Run cells 1–6 interactively (GPU check, clone, packages, Hugging Face access, helper), then
   **Save Version → Save & Run All (Commit)**. Each step runs in its own cell; its output stays under the
   cell and is also saved to `results/logs/<step>.log`.
6. Download `results.zip` from the last cell or the **Output** tab and unzip it as `results/` here. Kaggle results are in results_kaggle/results/

The notebook writes to a fresh `/kaggle/working/results`, never to the repository's own `results/`, so
outputs committed from an earlier machine are not reused. If a session ends early (12 h limit): new
version, **Add Input →** the previous version's output, set `RESUME = True`, run again; finished items
are skipped. Keep `BATCH_SIZE = 8` for the final run.

The notebook records the repository commit, the GPU and the start/end time in `results/logs/run_info.json`;
each model's exact commit, package versions and GPU per run are in `results/raw/<model>/run_manifest.json`
and `pip_freeze.txt`.

## Statistics used (deliberately simple)

- Rates: 95% z-interval, p ± 1.96·√(p(1−p)/n). Means: mean ± 1.96·SD/√n.
- Every yes/no comparison: McNemar chi-square with continuity correction, (|b − c| − 1)² / (b + c), from the b and c items whose outcome differs between the two conditions (always the same items).
- Confidence differences on the same items: paired Student t-test; two separate groups: two-sample Student t-test.
- Discrimination: ROC AUC with a z-interval (Hanley–McNeil standard error). Calibration: gap = mean confidence − accuracy.
- p-values are not corrected for the number of tests.

## Options every step accepts

- `--show-prompt` prints the exact prompts this step adds for row 0, then exits.
- Omit `--model` to re-analyse saved results without running a model.
- `--batch-size 4` if you run out of GPU memory.
- `--load-in-4bit` only if fp16 does not fit; then use it for every run of that model and report it
  (the scripts enforce this).
- `--retry-errors` regenerates items whose saved record has an error (the old record is kept).
- `--out DIR` writes somewhere other than `./results`.

Finished items are skipped on re-run, so an interrupted step can simply be started again.

## Outputs

Saved to `./results` relative to the working directory (`/kaggle/working/results` on Kaggle):

- `raw/dataset_manifest.json`: requested + resolved dataset revision, file SHA-256, subsets.
- `raw/<model>/<condition>.jsonl`: immutable generations, including failed ones.
- `raw/<model>/run_manifest.json`: model revision, settings, prompt fingerprints, and one entry per
  run with the GPU and package versions; `raw/<model>/pip_freeze.txt`: full environment.
- `raw/<model>/interp.jsonl`: interpretability outputs.
- `processed/records.csv`: one parsed row per model × item × condition.
- `summary_stepN_*.md`, `tables/*.csv`, `figures/*.png`: per-step results.
- `summary.md`: the full report from step 9.
