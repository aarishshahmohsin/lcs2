# LCS2 benchmark — results summary (auto-generated from saved artifacts)
Generated 2026-10-16T07:41:45.282043+00:00. Do not edit by hand; rerun the script.
- **llama**: `meta-llama/Llama-3.2-3B-Instruct` @ `0cb88a4f764b7a12671c53f0838cd831a0843b95`, dtype=float16, quant=None, transformers=5.20.0, torch=2.11.0+cu128, GPU=Tesla T4
- **qwen**: `Qwen/Qwen2.5-3B-Instruct` @ `aa8e72537993ba99e69dfaafa59ed015b17504d1`, dtype=float16, quant=None, transformers=5.20.0, torch=2.11.0+cu128, GPU=Tesla T4
- Dataset `Johndfm/MedMisBench-MentalHealth` rev `9757095`; seed 42; clean-prompt fingerprint `3016efcfb236`.

## Hypotheses (stated before analysis)

**H1 (misinformation susceptibility without uncertainty signal).** Appending the unverified misleading context lowers stress-set accuracy (McNemar chi-square p < 0.05) and, for items that flip correct→incorrect, verbal confidence does not drop by more than 5 points on average. Falsified if accuracy does not drop significantly, or if confidence on flipped items falls by > 5 points. (Tested in step 3.)
**H2 (vulnerability concentrates on uncertain items).** Clean-condition uncertainty (1 − forced-prefix probability of the predicted option) discriminates items on which the model adopts the misleading option: ROC AUC > 0.5 with the 95% z-interval excluding 0.5. Not supported if the interval includes 0.5 (a failure to find the effect, not proof that it is absent). (Tested in step 7.)
*Deviation from the original plan: H1 and H2 were first stated with an exact McNemar test and a bootstrap CI. Both were replaced after the first results by simpler tests (McNemar's chi-square with continuity correction instead of the exact binomial version; z-interval for the AUC); the thresholds are unchanged.*

## A. Baseline (Core set, rows 0–199, clean)

- **Accuracy (strict)**: parsed answer == gold; unparseable/invalid outputs count as wrong. Valid rate reported separately. CIs: 95% z-intervals, p ± 1.96·√(p(1−p)/n).
- **Verbal confidence**: the model's self-reported 0–100 number (not assumed calibrated). **Token confidence**: probability of the most likely option letter after the forced prefix `{"answer": "`, renormalised over the item's option letters (a model-internal score; computed on the identical prompt in a separate forward pass).
- **Calibration gap** = mean confidence − accuracy (both 0–1; positive = overconfident). **ROC AUC**: how well confidence separates correct from incorrect answers (0.5 = chance), with a 95% z-interval (Hanley–McNeil standard error).
- **Parse rule**: 1. Strip ``` fences; json.raw_decode at each '{'; first object with an "answer" key -> status 'json'. 2. Else regex on raw text: "answer": "<L>"  or  answer is/: <L> (L must be an uppercase letter) -> status 'regex'. 3. Else -> 'invalid'. Letter normalised ("(B)", "B.", "B) text" -> "B"). A letter not among    the item's option keys -> 'invalid_option'. Invalid answers count as incorrect. Confidence: number or numeric string in [0,100] ("85%" ok); never rescaled; (0,1] flagged. Repeated keys: answer/confidence use the last value (standard JSON); all "evidence" values are kept, joined with " | "; repeated keys are recorded in duplicate_keys (CONFLICTING_ANSWERS if they differ).

*Table `A_baseline.csv`*

| model   |   n | valid_rate                     | accuracy                      |   acc_among_valid |   token_argmax_acc |   mean_verbal_conf |   mean_token_conf |   calib_gap_verbal |   calib_gap_token | AUC_verbal           | AUC_token            |   gen_vs_token_agree | parse_status              |   option_letter_mass |
|:--------|----:|:-------------------------------|:------------------------------|------------------:|-------------------:|-------------------:|------------------:|-------------------:|------------------:|:---------------------|:---------------------|---------------------:|:--------------------------|---------------------:|
| llama   | 200 | 200/200 = 1.000 [1.000, 1.000] | 83/200 = 0.415 [0.347, 0.483] |             0.415 |              0.415 |               92.7 |             0.649 |              0.512 |             0.234 | 0.525 [0.443, 0.606] | 0.622 [0.542, 0.701] |                0.995 | {'json': 193, 'regex': 7} |                0.999 |
| qwen    | 200 | 200/200 = 1.000 [1.000, 1.000] | 57/200 = 0.285 [0.222, 0.348] |             0.285 |              0.285 |               87.8 |             0.938 |              0.592 |             0.653 | 0.578 [0.489, 0.668] | 0.592 [0.503, 0.681] |                1     | {'json': 200}             |                1     |

*Table `A_failure_patterns.csv`*

| model   | breakdown                  |   n | acc                                                                   |
|:--------|:---------------------------|----:|:----------------------------------------------------------------------|
| llama   | source=MEDMISQA            | 200 | 0.415                                                                 |
| llama   | n_options=6-7              |  46 | 0.283                                                                 |
| llama   | n_options=≤5               | 142 | 0.444                                                                 |
| llama   | n_options=≥8               |  12 | 0.583                                                                 |
| llama   | answer letter distribution | 200 | {'A': 35, 'B': 37, 'C': 51, 'D': 26, 'E': 43, 'F': 4, 'G': 3, 'H': 1} |
| llama   | gold letter distribution   | 200 | {'A': 39, 'B': 38, 'C': 41, 'D': 33, 'E': 33, 'F': 9, 'G': 4, 'H': 3} |
| qwen    | source=MEDMISQA            | 200 | 0.285                                                                 |
| qwen    | n_options=6-7              |  46 | 0.196                                                                 |
| qwen    | n_options=≤5               | 142 | 0.310                                                                 |
| qwen    | n_options=≥8               |  12 | 0.333                                                                 |
| qwen    | answer letter distribution | 200 | {'A': 33, 'B': 47, 'C': 34, 'D': 47, 'E': 25, 'F': 7, 'G': 4, 'H': 3} |
| qwen    | gold letter distribution   | 200 | {'A': 39, 'B': 38, 'C': 41, 'D': 33, 'E': 33, 'F': 9, 'G': 4, 'H': 3} |
