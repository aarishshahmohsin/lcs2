# AI Usage Declaration

**Project Title:** Responsible Medical LLMs for Mental Healthcare Benchmark
**Author:** Aarish Shah Mohsin
**Repository:** https://github.com/aarishshahmohsin/lcs2

---

## 1. Overview of AI Assistance
In accordance with the assignment guidelines, generative AI tools were used during the development,
benchmarking, statistical evaluation and report writing of this project. This file states what each
tool did, which checks were carried out with the AI's help, and which checks I carried out myself.
The full sessions are linked in Section 4.

---

## 2. Tools & Applications

| AI Tool | Provider | Primary Purpose / Role |
| :--- | :--- | :--- |
| **Claude Opus 5.5** (via Claude Code in VS Code; one part of the session used **Claude Fable 5**) | Anthropic | Drafted and debugged the benchmark scripts, audited them against the brief, refined the hypotheses (H1–H3), helped interpret results, drafted and revised the ACL report.
---

## 3. Specific Tasks & Verification

### A. Code development & debugging
* **What the AI did:**
  * Drafted the pipeline in `step1`–`step9`, `extra_reasoning.py`, `selftest.py` and `run_all.py`: dataset
    loading and validation, prompt and condition registry, JSON parser with regex fallback and
    repeated-key handling, local `transformers` generation in float16, occlusion and gradient×input
    attribution, and the logit lens.
  * Audited every script against the assignment brief and fixed what it found:
    * pinning the exact model revision across steps;
    * keeping a run history (GPU, package versions) in each run manifest;
    * counting invalid→invalid answers correctly;
    * deterministic (stable-sort) case selection.
  * Wrote the Kaggle notebook (`lcs2-assignment.ipynb`), which clones this repository, runs every step
    in its own cell and packages the results.
* **Checks done with the AI:**
  * `selftest.py` (prompt strings asserted against the brief, parser and leak-rule tests, full pipeline
    on synthetic data) was run after every code change.

### C. Report drafting & analysis
* **What the AI did:**
  * Drafted, rewrote and laid out the ACL report.
  * Selected and described the case studies, and wrote the review of the fairness flips.
  * Updated every number to the Kaggle T4 results.
* **Checks done with the AI:**
  * Every number, percentage, p-value and interval in the report was cross-checked by script against
    the CSV result tables produced by `step9_report.py`.
  * Every quoted model output and cited case was checked against the raw outputs.
* **Checks I did myself:**
  * Read the qualitative cases and the 19 counterfactual fairness flips cited in the report.
  * Reviewed the final text.

---

## 4. Shareable Chat / Session Links

* **Claude Code session (audit against the brief, statistics, Kaggle run, ACL report):** `traces/2026-10-16-144443-can-you-see-my-directories.txt`

---

## 5. Responsibility Statement
I remain fully responsible for every claim, formula, empirical result, table, figure and line of code
submitted in this repository and in the final PDF report.
