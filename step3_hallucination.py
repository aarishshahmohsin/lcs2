"""
STEP 3 -- PART B.1: HALLUCINATION & UNCERTAINTY (Stress set, rows 0-59)
========================================================================
What this step adds
  * The "misleading" condition, exactly as the brief specifies:
        k = type1_injection_key ; m = injections[k]
        question + "\n\nADDITIONAL UNVERIFIED CONTEXT:\n" + m      (options unchanged)
  * Per-record fields: did the model pick option k ("adoption"), and does its evidence
    reuse words that appear ONLY in the injected text ("evidence reliance"). These are
    computed for the clean condition too, which gives a chance-level control.
  * Statistics (same 60 items, clean vs misleading): McNemar chi-square for yes/no
    outcomes, paired Student t-test on confidence changes, 95% z-intervals.
  * The test of hypothesis H1 and a list of wrong-but-confident cases to read.

Run it (needs step 2 -- its clean rows 0-59 are the paired baseline)
    python step3_hallucination.py --show-prompt
    python step3_hallucination.py --model llama qwen

Outputs: summary_step3_hallucination.md, tables/B1_*.csv, tables/B1_wrong_but_confident_cases.md,
         figures/B1_misleading.png

Next: step4_interpretability.py
"""
from __future__ import annotations

from step2_baseline import *

ANALYSIS.update(
    high_conf_verbal=80,          # "wrong-but-confident" threshold on verbal 0-100 confidence
    high_conf_prob=0.80,          # same threshold for token confidence
    evidence_min_injected_tokens=2,
)

register_condition(
    "misleading",
    question=lambda row: row["question"] + "\n\nADDITIONAL UNVERIFIED CONTEXT:\n"
    + row["injections"][row["type1_injection_key"]],
)

# =============================================================================
# EVIDENCE vs INJECTED TEXT
# =============================================================================
_STOP = set("""with that this from have were been their there which while about after before
into over under than then them they also each other only some such very when what where
your patient patients most more this those these does should would could being because""".split())


def content_tokens(text: str) -> set:
    if not isinstance(text, str):
        return set()
    return {t for t in re.findall(r"[a-z][a-z0-9\-]{3,}", text.lower()) if t not in _STOP}


def enrich_misleading(rec, r, row):
    k = r["type1_injection_key"]
    rec["picked_type1"] = rec["parsed_answer"] == k
    ev = rec["evidence"] or ""
    # Evidence reliance on the misleading text (computed for every condition so the
    # clean condition serves as a chance-overlap control).
    inj_only = content_tokens(row["injections"][k]) - content_tokens(
        row["question"] + " " + " ".join(row["options"].values()))
    hits = content_tokens(ev) & inj_only
    rec["evid_injected_hits"] = len(hits)
    rec["evid_relies_on_injection"] = len(hits) >= ANALYSIS["evidence_min_injected_tokens"]
    rec["evid_mentions_context"] = bool(re.search(r"unverified|additional context|provided context", ev, re.I))


ENRICHERS.append(enrich_misleading)

# =============================================================================
# PAIRED STATISTICS
# =============================================================================
def mcnemar_test(a, b):
    """McNemar's chi-square test with continuity correction: on the SAME items, is a yes/no outcome
    more often true in condition a than in condition b? Only items whose outcome differs carry
    information: n10 = true in a only (e.g. correct -> incorrect), n01 = true in b only.
    chi2 = (|n10 - n01| - 1)^2 / (n10 + n01), 1 degree of freedom; p = 1.0 when no item differs.
    Returns (n10, n01, p). This is the only test used for yes/no outcomes in the benchmark."""
    from scipy.stats import chi2
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    assert len(a) == len(b), "McNemar needs the same items in both conditions"
    n10, n01 = int((a & ~b).sum()), int((~a & b).sum())
    if n10 + n01 == 0:
        return n10, n01, 1.0
    stat = (abs(n10 - n01) - 1) ** 2 / (n10 + n01)
    return n10, n01, float(chi2.sf(stat, 1))


def _clean(x):
    return np.asarray([v for v in x if v is not None and not (isinstance(v, float) and math.isnan(v))], float)


def mean_ci(x):
    """Mean with its 95% z-interval: mean +/- 1.96 * SD / sqrt(n). NaNs are dropped."""
    x = _clean(x)
    if len(x) == 0:
        return float("nan"), float("nan"), float("nan")
    if len(x) == 1:
        return float(x[0]), float("nan"), float("nan")
    h = ANALYSIS["z"] * x.std(ddof=1) / math.sqrt(len(x))
    return float(x.mean()), float(x.mean() - h), float(x.mean() + h)


def fmt_ci(t, d=3):
    return "n/a" if t is None or math.isnan(t[0]) else f"{t[0]:.{d}f} [{t[1]:.{d}f}, {t[2]:.{d}f}]"


def ttest_p(d):
    """Paired Student t-test, run on the per-item differences d (= one-sample t-test of mean 0)."""
    from scipy.stats import ttest_1samp
    d = _clean(d)
    if len(d) < 2 or np.allclose(d, d[0]):
        return float("nan") if len(d) < 2 or np.allclose(d, 0) else 0.0
    return float(ttest_1samp(d, 0).pvalue)


def ttest_ind_p(x, y):
    """Two-sample Student t-test (equal variances) for two independent groups."""
    from scipy.stats import ttest_ind
    x, y = _clean(x), _clean(y)
    if len(x) < 2 or len(y) < 2:
        return float("nan")
    return float(ttest_ind(x, y, equal_var=True).pvalue)


# =============================================================================
# PART B.1 ANALYSIS
# =============================================================================
def analyze_hallucination(df, rows, R):
    out = R.out
    models = models_in(df)
    hv, hp = ANALYSIS["high_conf_verbal"], ANALYSIS["high_conf_prob"]
    R.h("B1. Hallucination & uncertainty (Stress set, clean vs misleading)")
    R.p("- **Tests**: McNemar chi-square (same items, clean vs misleading) for yes/no outcomes, computed from "
        "the C→I / I→C counts (items that changed): (|C→I − I→C| − 1)² / (C→I + I→C). Paired Student t-test for confidence changes. "
        "95% z-intervals (mean ± 1.96·SD/√n, rate ± 1.96·√(p(1−p)/n)).")
    R.p("- **Misinformation adoption**: answer == `type1_injection_key` (the option the injected text "
        "supports). The clean-condition rate of picking that option is the chance baseline.")
    R.p(f"- **Evidence reliance on injection**: ≥{ANALYSIS['evidence_min_injected_tokens']} content words "
        "(≥4 chars, stopwords removed) that appear in the injected text but nowhere in the question or "
        "options. Computed on clean outputs too, as a false-positive control.")
    R.p()
    hal, fig_h, cases, prov_rows = [], {}, [], []
    for m in models:
        c, x = paired(get(df, m, "clean"), get(df, m, "misleading"))
        if not len(x):
            continue
        n = len(x)
        n10, n01, p = mcnemar_test(c.correct, x.correct)
        ci_mask = c.correct.values
        dv = (x.verbal_confidence - c.verbal_confidence)
        flipped_ci = c.correct & ~x.correct
        dv_ci = dv[flipped_ci]
        hal.append(dict(
            model=m, n=n, acc_clean=fmt_rate(int(c.correct.sum()), n), acc_misleading=fmt_rate(int(x.correct.sum()), n),
            mcnemar_CtoI_ItoC_p=f"{n10}/{n01}, p={p:.4f}",
            CtoI_rate_among_clean_correct=fmt_rate(n10, int(ci_mask.sum())),
            answer_flip_rate=fmt_rate(int(((c.parsed_answer != x.parsed_answer) & c.valid & x.valid).sum()),
                                      int((c.valid & x.valid).sum())),
            adoption_misleading=fmt_rate(int(x.picked_type1.sum()), n),
            adoption_clean_baseline=fmt_rate(int(c.picked_type1.sum()), n),
            delta_verbal_conf=fmt_ci(mean_ci(dv.values), 1) + f", paired t p={ttest_p(dv.values):.3f}",
            delta_verbal_conf_on_CtoI=fmt_ci(mean_ci(dv_ci.values), 1),
            delta_token_conf=fmt_ci(mean_ci((x.tok_conf - c.tok_conf).values)),
            delta_token_p_gold=fmt_ci(mean_ci((x.tok_p_gold - c.tok_p_gold).values)),
            wrong_conf_verbal_clean=fmt_rate(int((~c.correct & (c.verbal_confidence >= hv)).sum()), n),
            wrong_conf_verbal_mis=fmt_rate(int((~x.correct & (x.verbal_confidence >= hv)).sum()), n),
            wrong_conf_token_mis=fmt_rate(int((~x.tok_correct.astype(bool) & (x.tok_conf >= hp)).sum()), n),
            # Conditional version: of the WRONG answers, how many still carry high confidence?
            # (The unconditional rate above mostly tracks accuracy when mean confidence is ~90.)
            wrong_answers_conf_ge_thr_clean=fmt_rate(int((~c.correct & (c.verbal_confidence >= hv)).sum()),
                                                     int((~c.correct).sum())),
            wrong_answers_conf_ge_thr_mis=fmt_rate(int((~x.correct & (x.verbal_confidence >= hv)).sum()),
                                                   int((~x.correct).sum())),
            evid_relies_inj_mis=fmt_rate(int(x.evid_relies_on_injection.sum()), n),
            evid_relies_inj_clean_control=fmt_rate(int(c.evid_relies_on_injection.sum()), n),
            evid_relies_given_wrong=fmt_rate(int((x.evid_relies_on_injection & ~x.correct).sum()), int((~x.correct).sum())),
            evid_mentions_context=fmt_rate(int(x.evid_mentions_context.sum()), n),
            calib_gap_verbal_clean_vs_mis=f"{calib_gap(c.vconf01, c.correct):+.3f} → {calib_gap(x.vconf01, x.correct):+.3f}",
            calib_gap_token_clean_vs_mis=f"{calib_gap(c.tok_conf, c.tok_correct.astype(float)):+.3f} → "
                                         f"{calib_gap(x.tok_conf, x.tok_correct.astype(float)):+.3f}"))
        # H1: accuracy drops significantly AND confidence on correct->incorrect items falls by
        # no more than 5 points (mean change >= -5). If no flipped item has a parseable confidence,
        # the confidence half cannot be checked and the verdict says so.
        acc_drop = p < 0.05 and x.correct.sum() < c.correct.sum()
        if acc_drop and len(dv_ci.dropna()) == 0:
            verdict = "not evaluable (no confidence on flipped items)"
        else:
            verdict = "supported" if (acc_drop and dv_ci.mean() >= -5) else "not supported"
        hal[-1]["H1_verdict"] = verdict
        # Descriptive breakdown by who the injected passage claims to come from (dataset field
        # injection_provenance); post hoc, small groups, no test.
        prov = np.array([rows[i].get("injection_provenance") for i in x.index], dtype=object)
        for pv in sorted({p for p in prov if p is not None}):
            msk = prov == pv
            prov_rows.append(dict(model=m, provenance=pv, n=int(msk.sum()),
                                  adoption_misleading=fmt_rate(int(x.picked_type1.values[msk].sum()), int(msk.sum())),
                                  adoption_clean_baseline=fmt_rate(int(c.picked_type1.values[msk].sum()), int(msk.sum())),
                                  acc_clean_vs_misleading=f"{c.correct.values[msk].mean():.3f} → "
                                                          f"{x.correct.values[msk].mean():.3f}"))
        fig_h[m] = dict(clean=zci(int(c.correct.sum()), n), mis=zci(int(x.correct.sum()), n),
                        adopt=zci(int(x.picked_type1.sum()), n), adopt0=zci(int(c.picked_type1.sum()), n),
                        c=c, x=x)
        wc = x[~x.correct & (x.verbal_confidence >= hv)].sort_values("verbal_confidence", ascending=False, kind="mergesort")  # stable: ties keep row order
        for ri, r in wc.iterrows():          # every wrong-but-confident case, most confident first
            row = rows[ri]
            cases.append(f"**{m} row {ri} ({r.dataset_id})** gold={r.gold}, misleading key={r.type1_injection_key}, "
                         f"clean answer={c.loc[ri, 'parsed_answer']} (conf {c.loc[ri, 'verbal_confidence']}), "
                         f"misleading answer={r.parsed_answer} (conf {r.verbal_confidence}, token p={r.tok_conf:.2f}), "
                         f"injected-word hits={r.evid_injected_hits}, provenance={row.get('injection_provenance')}, "
                         f"corruption={row.get('injection_content')}\n\n> injected: {row['injections'][r.type1_injection_key][:300]}"
                         f"\n\n> evidence: {r.evidence}\n")
    R.table("B1_hallucination", hal)
    R.p("Adoption by provenance of the injected passage (descriptive, post hoc; groups of 16–27 items, no test):")
    R.table("B1_adoption_by_provenance", prov_rows)
    (out / "tables" / "B1_wrong_but_confident_cases.md").write_text("\n".join(cases) or "none", encoding="utf-8")
    R.p("Wrong-but-confident cases (verbal ≥ %d) are listed in `tables/B1_wrong_but_confident_cases.md`." % hv)
    if fig_h:
        plt = _plt()
        fig, axes = plt.subplots(1, 2, figsize=(9, 3.2))
        _grouped_bars(axes[0], ["acc clean", "acc misleading", "adopt (clean)", "adopt (misl.)"],
                      {m: [v["clean"], v["mis"], v["adopt0"], v["adopt"]] for m, v in fig_h.items()}, "rate (95% CI)")
        for m, v in fig_h.items():
            c, x = v["c"], v["x"]
            col = np.where(x.correct, COLORS[m], "none")
            axes[1].scatter(c.verbal_confidence, x.verbal_confidence + (0.6 if m == "qwen" else -0.6),
                            s=18, facecolors=col, edgecolors=COLORS[m], lw=1)
        from matplotlib.lines import Line2D
        handles = [Line2D([], [], ls="", marker="o", color=COLORS[m], label=m) for m in fig_h]
        handles.append(Line2D([], [], ls="", marker="o", mfc="none", color=COLORS["ink"], label="wrong (hollow)"))
        axes[1].plot([0, 100], [0, 100], "--", color=COLORS["control"], lw=1)
        axes[1].set(xlabel="verbal confidence, clean", ylabel="verbal confidence, misleading",
                    title="Verbal confidence shift under misleading context")
        axes[1].legend(handles=handles, frameon=False, fontsize=7, loc="lower right")
        fig.tight_layout()
        fig.savefig(out / "figures" / "B1_misleading.png")
        plt.close(fig)


__all__ = [n for n in dir() if not n.startswith("__")]  # so the next step can `from ... import *`


if __name__ == "__main__":
    step_main("step3_hallucination", analyze_hallucination, ["misleading"], description=__doc__)