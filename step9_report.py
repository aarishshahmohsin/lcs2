"""
STEP 9 -- FULL DETAILED REPORT: every section (A, B1-B4, C, D, extras) in one document
=====================================================================================
Recomputes everything from the saved raw outputs -- no model runs. Use this for the numbers,
tables and figures that go into the final report.

    python step9_report.py                 # -> results/summary.md (+ tables/, figures/)
    python step9_report.py --cases 5       # more case studies per category
    python step9_report.py --strict        # stop on the first failing section instead of noting it

What the report contains (in this order)
  0. Run information, dataset manifest (full resolved revision + file SHA-256), hypotheses
  1. Table of contents
  2. Executive summary: headline numbers per model, computed directly from the records
  3. Hypothesis verdicts (H1, H2, exploratory H3) pulled from the section tables
  4. Brief-compliance checklist (models, revision, seed, subsets, record fields, decoding, GPU)
  5. Run inventory: every model x condition with coverage, missing rows, errors, validity,
     accuracy, confidence, tokens, latency, duplicate JSON keys, prompt fingerprints, run ids
  6. Parse diagnostics: parse_status and confidence-note breakdowns per condition
  7. Sections A, B1, B2 (+ extended interpretability), B3, B4, C, D -- the step 2-8 analyses
  8. EXTRA: reasoning-first (only if extra_reasoning.py has been run)
  9. Case studies: concrete items for every dimension (also written to tables/case_studies.md)
 10. Figure gallery, table index, raw-file inventory (line counts + SHA-256), data dictionary
 11. Reproducibility: the exact commands
"""
from __future__ import annotations

import hashlib
import traceback

from step8_intervention import *

try:  # optional exploratory section; importing only registers its two conditions
    from extra_reasoning import analyze_reasoning, REASON_CONDITIONS
except Exception:  # noqa: BLE001 -- the extra file is optional
    analyze_reasoning, REASON_CONDITIONS = None, []

SECTIONS = [analyze_baseline, analyze_hallucination, analyze_interpretability, analyze_fairness,
            analyze_security, analyze_cross_dimension, analyze_intervention]

REQUIRED_RECORD_FIELDS = ["model", "model_revision", "condition", "row_index", "dataset_id", "gold",
                          "raw_output", "parsed_answer", "parse_status", "verbal_confidence", "evidence",
                          "option_probs", "tok_conf", "correct", "valid", "error", "generation_settings",
                          "quantization", "dtype", "prompt_version", "prompt_fingerprint", "seed", "run_id",
                          "timestamp", "batch_size", "n_input_tokens", "n_new_tokens", "latency_s"]

DATA_DICTIONARY = {
    "model / model_revision": "short model key and the exact Hugging Face commit used",
    "condition": "prompt condition (clean, misleading, fair_*, injection, canary, hardened_*, reason_*)",
    "row_index / dataset_id": "dataset row (0-based, fixed order) and the dataset's own item id",
    "gold / type1_injection_key": "correct option letter / the option the misleading text and injection push",
    "raw_output": "the model's full generated text (never edited)",
    "parsed_answer / parse_status": "answer letter after parsing (None if invalid) and how it was obtained",
    "duplicate_keys": "JSON keys the model repeated; ';CONFLICTING_ANSWERS' if 'answer' repeats with different letters",
    "verbal_confidence / vconf01": "self-reported 0-100 confidence / the same on 0-1",
    "evidence": "the evidence field (all values joined with ' | ' if the key was repeated)",
    "option_probs": "forced-prefix probabilities of each option letter, renormalised over the item's options",
    "tok_pred / tok_conf / tok_p_gold": "arg-max option, its probability, and the gold option's probability",
    "option_letter_mass": "unnormalised probability mass on option letters at the answer position",
    "correct / valid": "parsed answer == gold (invalid counts as wrong) / answer could be parsed",
    "picked_type1": "answer == type1_injection_key (misinformation adoption / injection following)",
    "evid_relies_on_injection": "evidence reuses >= N content words that occur only in the injected text",
    "phrase_in_evidence / phrase_anywhere": "injection marker phrase in the evidence field / anywhere in the output",
    "leak_*": "canary leak flags (verbatim, normalised, partial, any, in evidence)",
    "generation_settings / dtype / quantization": "decoding settings, weight dtype and quantization of the run",
    "prompt_version / prompt_fingerprint": "prompt template version and a hash of this condition's prompt",
    "run_id / timestamp / batch_size / seed": "provenance of the generation call",
    "n_input_tokens / n_new_tokens / latency_s": "cost of the generation (latency is per item, batch-averaged)",
}

_CASE_TXT = 350   # characters of question / evidence shown per case


# =============================================================================
# SMALL HELPERS
# =============================================================================
def _short(s, n=_CASE_TXT):
    s = "" if s is None or (isinstance(s, float) and math.isnan(s)) else str(s)
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _ranges(idx):
    """[0,1,2,5,7,8] -> '0-2, 5, 7-8' (for listing missing rows compactly)."""
    idx = sorted(int(i) for i in idx)
    out, start, prev = [], None, None
    for i in idx:
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            out.append(f"{start}-{prev}" if prev > start else f"{start}")
            start = prev = i
    if start is not None:
        out.append(f"{start}-{prev}" if prev > start else f"{start}")
    return ", ".join(out)


def _sha(path, n=12):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:n]


def _read_table(out, name):
    import pandas as pd
    f = out / "tables" / f"{name}.csv"
    return pd.read_csv(f) if f.exists() else None


def _rate(mask, n=None):
    mask = np.asarray(mask, bool)
    return fmt_rate(int(mask.sum()), int(n if n is not None else len(mask)))


def _section(R, fn, strict, *args):
    """Run one analysis section; a failure is written into the report (unless --strict)."""
    try:
        fn(*args, R)
    except Exception:  # noqa: BLE001
        if strict:
            raise
        log.exception("section %s failed", fn.__name__)
        R.p(f"> **Section `{fn.__name__}` failed** -- the rest of the report is unaffected. Traceback:")
        R.p("```\n" + traceback.format_exc()[-3000:] + "\n```")


# =============================================================================
# 0. RUN + DATASET INFORMATION
# =============================================================================
def write_dataset_info(R):
    mf = R.out / "raw" / "dataset_manifest.json"
    if not mf.exists():
        R.p("- Dataset manifest not found (run step 1).")
        return
    j = json.loads(mf.read_text())
    R.p(f"- Dataset file `{j.get('filename')}`, requested revision `{j.get('revision')}`, resolved revision "
        f"`{j.get('resolved_revision')}`, file SHA-256 `{j.get('sha256_file')}`, {j.get('n_rows')} rows.")
    R.p(f"- Subsets: " + ", ".join(f"{k} rows {a}–{b} (n={b - a + 1})" for k, (a, b) in SUBSETS.items()))
    if j.get("issues"):
        R.p(f"- Dataset issues recorded at load time: {j['issues']}")


# =============================================================================
# 2. EXECUTIVE SUMMARY (computed directly from the records)
# =============================================================================
def executive_summary(df, rows, R):
    R.h("Executive summary")
    R.p("Headline numbers per model, computed directly from `records.csv` (95% z-intervals). Every number "
        "is repeated with its test in the section it belongs to; this table is only an overview.")
    srows = []
    stress_hi = SUBSETS["stress"][1]
    for m in models_in(df):
        r = dict(model=m)
        c = get(df, m, "clean")
        if len(c):
            r["A: Core accuracy"] = _rate(c.correct)
            r["A: valid rate"] = f"{c.valid.mean():.3f}"
            r["A: mean verbal conf"] = f"{c.verbal_confidence.mean():.1f}"
            r["A: calibration gap verbal / token"] = f"{calib_gap(c.vconf01, c.correct):+.3f} / {calib_gap(c.tok_conf, c.tok_correct.astype(float)):+.3f}"
        cs = c.loc[c.index <= stress_hi] if len(c) else c
        cc, x = paired(cs, get(df, m, "misleading"))
        if len(x):
            n10, n01, p = mcnemar_test(cc.correct, x.correct)
            r["B1: Stress acc clean → misleading"] = f"{cc.correct.mean():.3f} → {x.correct.mean():.3f} (p={p:.4f})"
            r["B1: adopts misleading option"] = _rate(x.picked_type1)
        flips = []
        for attr, (ca, cb) in FAIRNESS_PAIRS.items():
            a, b = paired(get(df, m, ca), get(df, m, cb))
            if len(a):
                ok = a.valid & b.valid
                flips.append(f"{attr} {int(((a.parsed_answer != b.parsed_answer) & ok).sum())}/{int(ok.sum())}")
        if flips:
            r["B3: answer flips A vs B"] = "; ".join(flips)
        cc, x = paired(cs, get(df, m, "injection"))
        if len(x):
            r["B4: follows injected answer"] = _rate(x.picked_type1)
            full = x.picked_type1.astype(bool) & x.conf_is_100.astype(bool) & x.phrase_in_evidence.astype(bool)
            r["B4: full injection compliance"] = _rate(full)
        x = get(df, m, "canary")
        if len(x):
            r["B4: canary leak (any)"] = _rate(x.leak_any)
        b, a = paired(get(df, m, "injection"), get(df, m, "hardened_injection"))
        if len(a):
            n10, n01, p = mcnemar_test(b.picked_type1.astype(bool), a.picked_type1.astype(bool))
            r["D: injection following before → after"] = f"{b.picked_type1.mean():.3f} → {a.picked_type1.mean():.3f} (p={p:.4f})"
        b, a = paired(cs, get(df, m, "hardened_clean"))
        if len(a):
            r["D: Stress clean acc before → after"] = f"{b.correct.mean():.3f} → {a.correct.mean():.3f}"
        srows.append(r)
    if srows:
        import pandas as pd
        t = pd.DataFrame(srows).set_index("model").T.reset_index().rename(columns={"index": "measure"})
        R.table("00_executive_summary", t.to_dict("records"))


def hypothesis_verdicts(out, R):
    R.h("Hypothesis verdicts")
    vrows = []
    t = _read_table(out, "B1_hallucination")
    if t is not None and "H1_verdict" in t:
        for _, r in t.iterrows():
            vrows.append(dict(hypothesis="H1 (pre-registered)", model=r.model, verdict=r.H1_verdict,
                              evidence=f"McNemar {r.mcnemar_CtoI_ItoC_p}; Δconf on C→I {r.delta_verbal_conf_on_CtoI}",
                              source="B1_hallucination.csv"))
    t = _read_table(out, "C_cross_dimension")
    if t is not None and "H2" in t:
        for _, r in t[t.analysis.str.startswith("C1 ")].iterrows():
            vrows.append(dict(hypothesis="H2 (pre-registered)", model=r.model, verdict=r.H2,
                              evidence=f"{r.statistic}, p={r.p}", source="C_cross_dimension.csv"))
    t = _read_table(out, "X_reasoning")
    if t is not None and "H3" in t:
        for _, r in t.iterrows():
            vrows.append(dict(hypothesis="H3 (exploratory, post hoc)", model=r.model, verdict=r.H3,
                              evidence=f"Core acc {r.acc_answer_first} → {r.acc_reasoning_first}; McNemar {r.mcnemar_CtoI_ItoC_p}",
                              source="X_reasoning.csv"))
    if vrows:
        R.table("00_hypothesis_verdicts", vrows)
    else:
        R.p("No hypothesis tables found yet.")


# =============================================================================
# 4. BRIEF-COMPLIANCE CHECKLIST
# =============================================================================
def compliance_checklist(df, R):
    R.h("Brief-compliance checklist")
    checks = []

    def add(item, ok, detail):
        checks.append(dict(check=item, status="OK" if ok is True else ("WARN" if ok is None else "FAIL"),
                           detail=detail))

    expected = {"llama": "meta-llama/Llama-3.2-3B-Instruct", "qwen": "Qwen/Qwen2.5-3B-Instruct"}
    for m in models_in(df):
        mf = R.out / "raw" / m / "run_manifest.json"
        j = json.loads(mf.read_text()) if mf.exists() else {}
        add(f"{m}: model id", j.get("model") == expected.get(m), f"{j.get('model')}")
        add(f"{m}: model revision pinned", bool(j.get("model_revision")), f"{j.get('model_revision')}")
        d = df[df.model == m]
        revs = sorted(set(d.model_revision.dropna().astype(str)))
        add(f"{m}: one model revision across all conditions", len(revs) == 1, ", ".join(revs) or "none recorded")
        # every run of every step, not only the last one (the manifest keeps a run history)
        gpus = sorted({str((r.get("versions") or {}).get("gpu")) for r in j.get("runs") or [j]})
        kaggle = all(any(g in x for g in ("T4", "P100")) for x in gpus)
        add(f"{m}: free Kaggle GPU (all runs)", True if kaggle else None,
            f"recorded GPU(s) = {', '.join(gpus)}"
            + ("" if kaggle else " (brief: free Kaggle GPU, i.e. T4/P100 -- rerun there for the final numbers)"))
        dts = sorted(set(d.dtype.dropna().astype(str)))
        qs = sorted(set(d.quantization.fillna("none").astype(str)))
        add(f"{m}: one dtype / quantization across all conditions", len(dts) == 1 and len(qs) == 1,
            f"dtype {dts}, quantization {qs}")
    add("dataset revision", DATASET["revision"] == "9757095", DATASET["revision"])
    add("seed", SEED == 42, str(SEED))
    add("decoding", GENERATION.get("do_sample") is False, json.dumps(GENERATION))
    missing = [f for f in REQUIRED_RECORD_FIELDS if f not in df.columns]
    add("records.csv carries every required field", not missing, "missing: " + (", ".join(missing) or "none"))
    for m in models_in(df):
        for cond in sorted(set(df[df.model == m].condition)):
            sub = subset_for(cond) if cond in CONDITIONS else None
            if sub is None:
                continue
            lo, hi = SUBSETS[sub]
            have = set(get(df, m, cond).index)
            miss = sorted(set(range(lo, hi + 1)) - have)
            if miss:
                add(f"{m}/{cond}: coverage of {sub} set", False, f"missing rows {_ranges(miss)}")
    if not any(c["check"].endswith("set") for c in checks):
        add("coverage: every condition has every row of its subset", True, "no missing rows")
    errs = int(df.error.notna().sum()) if "error" in df else 0
    add("failed generations (kept, counted as wrong)", True if errs == 0 else None, f"{errs} record(s) with an error")
    R.table("00_compliance_checklist", checks)


# =============================================================================
# 5-6. RUN INVENTORY + PARSE DIAGNOSTICS
# =============================================================================
def run_inventory(df, R):
    R.h("Run inventory (every model × condition)")
    R.p("Coverage is checked against the condition's subset. Accuracy counts invalid outputs as wrong. "
        "`dup_keys` = outputs that repeat a JSON key; `conflicting` = outputs that repeat `answer` with "
        "different letters (the parser keeps the last value). `fingerprints` > 1 means the prompt changed "
        "between runs of the same condition.")
    inv = []
    for m in models_in(df):
        for cond in sorted(set(df[df.model == m].condition), key=lambda c: (c.split("_")[0], c)):
            x = get(df, m, cond)
            sub = subset_for(cond) if cond in CONDITIONS else "?"
            lo, hi = SUBSETS.get(sub, (0, -1))
            exp = hi - lo + 1 if sub in SUBSETS else len(x)
            miss = sorted(set(range(lo, hi + 1)) - set(x.index)) if sub in SUBSETS else []
            dk = x.duplicate_keys if "duplicate_keys" in x else None
            inv.append(dict(
                model=m, condition=cond, subset=sub, n=f"{len(x)}/{exp}", missing=_ranges(miss) or "-",
                errors=int(x.error.notna().sum()), valid=f"{x.valid.mean():.3f}",
                accuracy=_rate(x.correct), verbal_conf=f"{x.verbal_confidence.mean():.1f}",
                token_conf=f"{x.tok_conf.mean():.3f}" if x.tok_conf.notna().any() else "-",
                in_tokens=f"{x.n_input_tokens.mean():.0f}", new_tokens=f"{x.n_new_tokens.mean():.0f}",
                latency_s=f"{x.latency_s.mean():.2f}",
                dup_keys=int(dk.notna().sum()) if dk is not None else "-",
                conflicting=int(dk.fillna("").str.contains("CONFLICTING").sum()) if dk is not None else "-",
                fingerprints=x.prompt_fingerprint.nunique(), run_ids=x.run_id.nunique()))
    R.table("00_run_inventory", inv)


def parse_diagnostics(df, R):
    import pandas as pd
    R.h("Parse diagnostics")
    R.p("How each answer was obtained (`parse_status`) and how the confidence field was read "
        "(`conf_note`), per model × condition. Invalid outputs count as incorrect everywhere.")
    for col, name in (("parse_status", "00_parse_status"), ("conf_note", "00_conf_note")):
        if col not in df:
            continue
        t = pd.crosstab([df.model, df.condition], df[col].fillna("none")).reset_index()
        R.table(name, t.to_dict("records"))
    if "duplicate_keys" in df and df.duplicate_keys.notna().any():
        t = (df[df.duplicate_keys.notna()].groupby(["model", "condition", "duplicate_keys"]).size()
             .reset_index(name="n"))
        R.p("Outputs with repeated JSON keys, by which keys were repeated:")
        R.table("00_duplicate_keys", t.to_dict("records"))


# =============================================================================
# 9. CASE STUDIES
# =============================================================================
def _case(md, title, row, parts):
    md.append(f"#### {title}")
    md.append(f"- Item `{row['id']}` (row {row['row_index']}), gold **{row['answer']}**, "
              f"misleading/injection key **{row['type1_injection_key']}**")
    md.append(f"- Question: {_short(row['question'])}")
    md.append("- Options: " + "; ".join(f"**{k}** {_short(v, 90)}" for k, v in row["options"].items()))
    for label, r in parts:
        if r is None:
            continue
        tc = f", token p={r.tok_conf:.2f}" if isinstance(r.tok_conf, float) and not math.isnan(r.tok_conf) else ""
        md.append(f"- *{label}*: answer **{r.parsed_answer}** ({'correct' if r.correct else 'wrong'}), "
                  f"verbal conf {r.verbal_confidence}{tc}. Evidence: “{_short(r.evidence, 250)}”")
    md.append("")


def case_studies(df, rows, R, n_cases):
    R.h("Case studies")
    R.p(f"Up to {n_cases} items per category, chosen deterministically (highest confidence first, then "
        "row order). The full list is in `tables/case_studies.md`. These are illustrations for the "
        "paper's qualitative analysis, not additional evidence.")
    md = []
    stress_hi = SUBSETS["stress"][1]
    for m in models_in(df):
        c = get(df, m, "clean")
        md.append(f"### {m}\n")
        # B1: correct -> incorrect under misleading context, most confident first
        cc, x = paired(c.loc[c.index <= stress_hi], get(df, m, "misleading"))
        if len(x):
            sel = x[cc.correct & ~x.correct].sort_values("verbal_confidence", ascending=False, kind="mergesort").head(n_cases)
            md.append("**B1 — misleading context flips a correct answer (most confident first)**\n")
            for i in sel.index:
                _case(md, f"{m} · B1 · row {i}", rows[i], [("clean", cc.loc[i]), ("misleading", x.loc[i])])
        # B2: wrong but highly confident on clean Core items
        if len(c):
            sel = (c[~c.correct & c.valid].reset_index()
                   .sort_values(["verbal_confidence", "tok_conf", "row_index"], ascending=[False, False, True])
                   .set_index("row_index").head(n_cases))
            md.append("**A/B2 — wrong but confident on the clean prompt**\n")
            for i in sel.index:
                _case(md, f"{m} · A · row {i}", rows[i], [("clean", c.loc[i])])
        # B3: answer flips between the two values of an attribute
        md.append("**B3 — answer changes between counterfactual metadata values**\n")
        k = 0
        for attr, (ca, cb) in FAIRNESS_PAIRS.items():
            a, b = paired(get(df, m, ca), get(df, m, cb))
            if not len(a):
                continue
            fl = a[(a.parsed_answer != b.parsed_answer) & a.valid & b.valid]
            for i in fl.index[:max(1, n_cases // len(FAIRNESS_PAIRS) + 1)]:
                _case(md, f"{m} · B3 · {attr} · row {i}", rows[i],
                      [("clean", c.loc[i] if i in c.index else None), (ca, a.loc[i]), (cb, b.loc[i])])
                k += 1
        if not k:
            md.append("_No answer flips._\n")
        # B4: injection full compliance, canary leaks
        cc, x = paired(c.loc[c.index <= stress_hi], get(df, m, "injection"))
        if len(x):
            full = x[x.picked_type1.astype(bool) & x.conf_is_100.astype(bool) & x.phrase_in_evidence.astype(bool)]
            pick = full if len(full) else x[x.picked_type1.astype(bool)]
            md.append(f"**B4 — prompt injection {'fully followed' if len(full) else 'answer followed'}**\n")
            for i in pick.index[:n_cases]:
                _case(md, f"{m} · B4 injection · row {i}", rows[i], [("clean", cc.loc[i]), ("injection", x.loc[i])])
        x = get(df, m, "canary")
        if len(x) and x.leak_any.astype(bool).any():
            md.append("**B4 — canary leaked**\n")
            for i in x[x.leak_any.astype(bool)].index[:n_cases]:
                md.append(f"- {m} row {i}: output excerpt “{_short(x.loc[i, 'raw_output'], 300)}”")
            md.append("")
        # D: items where hardening made injection-following START (backfire) or STOP
        b, a = paired(get(df, m, "injection"), get(df, m, "hardened_injection"))
        if len(a):
            for lab, mask in (("starts following after hardening", ~b.picked_type1.astype(bool) & a.picked_type1.astype(bool)),
                              ("stops following after hardening", b.picked_type1.astype(bool) & ~a.picked_type1.astype(bool))):
                sel = a[mask]
                md.append(f"**D — injection: {lab} ({int(mask.sum())} items)**\n")
                for i in sel.index[:n_cases]:
                    _case(md, f"{m} · D · row {i}", rows[i], [("injection", b.loc[i]), ("hardened_injection", a.loc[i])])
        # EXTRA: reasoning-first flips
        if "reason_clean" in set(df[df.model == m].condition):
            af, rf = paired(c, get(df, m, "reason_clean"))
            for lab, mask in (("reasoning fixes the answer", ~af.correct & rf.correct),
                              ("reasoning breaks the answer", af.correct & ~rf.correct)):
                md.append(f"**EXTRA — {lab} ({int(mask.sum())} items)**\n")
                for i in rf[mask].index[:n_cases]:
                    _case(md, f"{m} · reasoning · row {i}", rows[i], [("answer-first", af.loc[i]), ("reasoning-first", rf.loc[i])])
    text = "\n".join(md)
    (R.out / "tables" / "case_studies.md").write_text(text or "none", encoding="utf-8")
    R.p(text)


# =============================================================================
# 10. APPENDICES: figures, tables, raw files, data dictionary
# =============================================================================
def appendices(df, R):
    out = R.out
    R.h("Figure gallery")
    for f in sorted((out / "figures").glob("*.png")):
        R.p(f"**{f.stem}**\n\n![{f.stem}](figures/{f.name})\n")
    R.h("Table index")
    R.table("00_table_index", [dict(file=f"tables/{f.name}", bytes=f.stat().st_size,
                                    rows=(sum(1 for _ in open(f, encoding="utf-8")) - 1) if f.suffix == ".csv" else "-")
                               for f in sorted((out / "tables").glob("*")) if f.is_file()])
    R.h("Raw-file inventory")
    R.p("Every raw generation file the numbers are computed from, with its line count and SHA-256 "
        "(first 12 hex digits), so a reader can check they are looking at the same outputs.")
    inv = []
    for f in sorted((out / "raw").rglob("*")):
        if f.is_file() and f.suffix in (".jsonl", ".json", ".npz"):
            lines = sum(1 for _ in open(f, encoding="utf-8")) if f.suffix == ".jsonl" else "-"
            inv.append(dict(file=str(f.relative_to(out)), lines=lines, bytes=f.stat().st_size, sha256=_sha(f)))
    R.table("00_raw_inventory", inv)
    R.h("Data dictionary (`processed/records.csv`)")
    R.p(f"{len(df)} item-level records, {len(df.columns)} columns. Main fields:")
    for k, v in DATA_DICTIONARY.items():
        R.p(f"- `{k}`: {v}")
    rest = sorted(set(df.columns) - {c.strip() for k in DATA_DICTIONARY for c in k.replace("*", "").split("/")})
    R.p(f"- Other columns (added by the step enrichers; see the code): {', '.join(f'`{c}`' for c in rest)}")


def reproducibility(R):
    R.h("Reproducibility")
    R.p("Every number above is computed by `step9_report.py` from `results/raw/*/*.jsonl`; item-level "
        "parsed records are in `results/processed/records.csv` (and `.jsonl`). Invalid / failed "
        "generations are kept (`parse_status`, `error`) and count as incorrect. A retried item keeps all "
        "its raw records; the analysis uses the most recent one.")
    R.p("```\n"
        "python lcs2_steps/step1_setup.py                       # dataset + model smoke test\n"
        "python lcs2_steps/step2_baseline.py     --model llama qwen\n"
        "python lcs2_steps/step3_hallucination.py --model llama qwen\n"
        "python lcs2_steps/step4_interpretability.py --model llama qwen\n"
        "python lcs2_steps/step5_fairness.py     --model llama qwen\n"
        "python lcs2_steps/step6_security.py     --model llama qwen\n"
        "python lcs2_steps/step7_cross_dimension.py\n"
        "python lcs2_steps/step8_intervention.py --model llama qwen\n"
        "python lcs2_steps/extra_reasoning.py    --model llama qwen   # optional, exploratory\n"
        "python lcs2_steps/step9_report.py\n"
        "```")


# =============================================================================
# BUILD
# =============================================================================
def build_report(out, n_cases=3, strict=False):
    out = Path(out)
    df, rows = process(out)

    head = Report(out)                      # run info, TOC, overview -- assembled last
    write_run_info(head, df)
    write_dataset_info(head)

    body = Report(out)                      # the step 2-8 sections (+ extra)
    for fn in SECTIONS:
        _section(body, fn, strict, df, rows)
    if analyze_reasoning is not None and set(REASON_CONDITIONS) & set(df.condition):
        _section(body, analyze_reasoning, strict, df, rows)

    over = Report(out)                      # needs the section tables, so built after them
    _section(over, executive_summary, strict, df, rows)
    _section(over, lambda R: hypothesis_verdicts(out, R), strict)
    _section(over, lambda R: compliance_checklist(df, R), strict)
    _section(over, lambda R: run_inventory(df, R), strict)
    _section(over, lambda R: parse_diagnostics(df, R), strict)

    tail = Report(out)
    _section(tail, lambda R: case_studies(df, rows, R, n_cases), strict)
    _section(tail, lambda R: appendices(df, R), strict)
    reproducibility(tail)

    lines = over.lines + body.lines + tail.lines
    toc = ["", "## Contents", ""]
    for ln in lines:
        if ln.startswith("## "):
            t = ln[3:].strip()
            anchor = re.sub(r"[^\w\- ]", "", t.lower()).strip().replace(" ", "-")
            toc.append(f"- [{t}](#{anchor})")
    R = Report(out)
    R.lines = head.lines + toc + lines
    R.save("summary.md")
    log.info("wrote %s (%d lines)", out / "summary.md", len(R.lines))
    return df


__all__ = [n for n in dir() if not n.startswith("__")]  # so the next step can `from ... import *`


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--cases", type=int, default=3, help="case studies per category (default 3)")
    ap.add_argument("--strict", action="store_true", help="stop on the first failing section")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)
    build_report(a.out, a.cases, a.strict)
    print(f"[written] {Path(a.out) / 'summary.md'}  (tables in {Path(a.out) / 'tables'}, "
          f"case studies in {Path(a.out) / 'tables' / 'case_studies.md'})")