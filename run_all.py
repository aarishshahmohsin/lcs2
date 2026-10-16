"""
RUN ALL -- every benchmark step, one after the other, in the order of the brief
==============================================================================
Runs each step as its own process (so each one loads and frees its own model, one model at a
time) and stops at the first failing step. Every step resumes, so after a crash or a Kaggle
session timeout just run the same command again: finished items are skipped.

    python run_all.py                              # selftest, steps 1-9 + extra, both models
    python run_all.py --model llama                # one model only
    python run_all.py --from step5                 # resume the sequence at step 5
    python run_all.py --only step3 step6           # just these steps (step 9 is not added)
    python run_all.py --no-extra                   # skip the exploratory reasoning-first run
    python run_all.py --analysis-only              # no model runs: re-analyse saved results

The console output of every step is also appended to <out>/run_all.log, with the start time,
duration and exit code of each step.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

# name, file, takes --model, takes the shared run options (--load-in-4bit, --batch-size, --data-file)
STEPS = [
    ("selftest", "selftest.py", False, False),
    ("step1", "step1_setup.py", True, True),
    ("step2", "step2_baseline.py", True, True),
    ("step3", "step3_hallucination.py", True, True),
    ("step4", "step4_interpretability.py", True, True),
    ("step5", "step5_fairness.py", True, True),
    ("step6", "step6_security.py", True, True),
    ("step7", "step7_cross_dimension.py", False, False),   # analysis only, no model
    ("step8", "step8_intervention.py", True, True),
    ("extra", "extra_reasoning.py", True, True),           # exploratory (H3)
    ("step9", "step9_report.py", False, False),            # full report from saved results
]
NAMES = [s[0] for s in STEPS]


def command(step, a):
    name, file, takes_model, takes_run_opts = step
    cmd = [sys.executable, str(HERE / file)]
    if name == "selftest":
        return cmd
    cmd += ["--out", a.out]
    if takes_model and a.model and not a.analysis_only:
        cmd += ["--model", *a.model]
    if takes_run_opts:
        if a.load_in_4bit:
            cmd.append("--load-in-4bit")
        if a.batch_size:
            cmd += ["--batch-size", str(a.batch_size)]
        if a.data_file:
            cmd += ["--data-file", a.data_file]
    if name == "step1" and (a.analysis_only or not a.model):
        cmd = [sys.executable, str(HERE / file), "--out", a.out] + (["--data-file", a.data_file] if a.data_file else [])
    if name == "step9" and a.strict:
        cmd.append("--strict")
    return cmd


def run(cmd, log):
    """Run one step, streaming its output to the console and to the log file."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in p.stdout:
        sys.stdout.write(line)
        log.write(line)
    return p.wait()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", nargs="*", default=["llama", "qwen"], choices=["llama", "qwen"])
    ap.add_argument("--out", default="results")
    ap.add_argument("--from", dest="start", choices=NAMES, help="start the sequence at this step")
    ap.add_argument("--only", nargs="*", choices=NAMES, help="run only these steps, in pipeline order")
    ap.add_argument("--no-extra", action="store_true", help="skip the exploratory reasoning-first experiment")
    ap.add_argument("--no-selftest", action="store_true")
    ap.add_argument("--analysis-only", action="store_true", help="no model runs; re-analyse saved results")
    ap.add_argument("--load-in-4bit", action="store_true", help="NF4; only if fp16 does not fit (all steps)")
    ap.add_argument("--batch-size", type=int, default=None)
    ap.add_argument("--data-file", default=None, help="local JSONL copy of the fixed dataset revision")
    ap.add_argument("--strict", action="store_true", help="step 9 stops on the first failing section")
    ap.add_argument("--keep-going", action="store_true", help="continue with the next step after a failure")
    a = ap.parse_args()

    steps = STEPS
    if a.start:
        steps = steps[NAMES.index(a.start):]
    if a.only:
        steps = [s for s in steps if s[0] in a.only]
    if a.no_extra:
        steps = [s for s in steps if s[0] != "extra"]
    if a.no_selftest:
        steps = [s for s in steps if s[0] != "selftest"]

    Path(a.out).mkdir(parents=True, exist_ok=True)
    results = []
    with open(Path(a.out) / "run_all.log", "a", encoding="utf-8") as log:
        log.write(f"\n===== run_all {datetime.now(timezone.utc).isoformat()} argv={sys.argv[1:]} =====\n")
        for step in steps:
            cmd = command(step, a)
            banner = f"\n{'#' * 70}\n# {step[0]}: {' '.join(Path(c).name if c.endswith('.py') else c for c in cmd[1:])}\n{'#' * 70}\n"
            sys.stdout.write(banner)
            log.write(banner)
            log.flush()
            t0 = time.time()
            code = run(cmd, log)
            dt = time.time() - t0
            results.append((step[0], code, dt))
            msg = f"[run_all] {step[0]} finished with exit code {code} in {dt / 60:.1f} min\n"
            sys.stdout.write(msg)
            log.write(msg)
            log.flush()
            if code != 0 and not a.keep_going:
                break
        summary = "\n[run_all] summary\n" + "\n".join(
            f"  {n:<9} {'OK' if c == 0 else f'FAILED ({c})':<12} {d / 60:6.1f} min" for n, c, d in results)
        skipped = [s[0] for s in steps[len(results):]]
        if skipped:
            summary += (f"\n  not run: {', '.join(skipped)}\n  fix the failure, then continue with: "
                        f"python run_all.py --from {results[-1][0]}")
        print(summary)
        log.write(summary + "\n")
    sys.exit(0 if all(c == 0 for _, c, _ in results) else 1)


if __name__ == "__main__":
    main()
