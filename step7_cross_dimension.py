"""
STEP 7 -- PART C: CROSS-DIMENSION ANALYSIS (Stress set, no new model runs)
=========================================================================
What this step adds -- joins the earlier results on row_index and tests relationships:
  C1 (= hypothesis H2): does clean-condition uncertainty (1 - token confidence) predict which
     items the model is misled on? ROC AUC with a 95% z-interval (Hanley-McNeil) and z-test p.
  C2: does the same uncertainty predict prompt-injection answer-following?
  C3: are misleading-context failures overconfident? Verbal confidence on items that flip
     correct->incorrect vs items that stay correct (two-sample Student t-test).
  C4: on the same items, does the misleading passage or the explicit injection move more answers
     onto k? McNemar test (chooses k under misleading vs under injection); the overlap counts
     (both / misleading only / injection only / neither) are reported as description.
  Per model, never pooled (the two models' confidence scales are not comparable).

Run it (after steps 2, 3, 5 and 6)
    python step7_cross_dimension.py

Outputs: summary_step7_cross_dimension.md, tables/C_cross_dimension.csv, figures/C_cross.png

Next: step8_intervention.py
"""
from __future__ import annotations

from step6_security import *


def _auc_row(m, analysis, score, label, **extra):
    (au, lo, hi), p = auroc_ci(score, label)
    return dict(model=m, analysis=analysis, n=int(len(label)), positives=int(np.asarray(label, bool).sum()),
                statistic=f"AUC {au:.3f} [{lo:.3f}, {hi:.3f}]", p=f"{p:.4f}", **extra)


# =============================================================================
# PART C ANALYSIS
# =============================================================================
def analyze_cross_dimension(df, rows, R):
    out = R.out
    models = models_in(df)
    R.h("C. Cross-dimension analysis (Stress set, joined on row_index)")
    R.p("C1 (tests H2): does clean uncertainty (1 − token confidence) predict misinformation adoption? "
        "ROC AUC = P(an adopted item is more uncertain than a non-adopted item); 95% z-interval with the "
        "Hanley–McNeil standard error, z-test of AUC = 0.5. C2: same predictor for injection "
        "answer-following. C3: are misleading-context failures overconfident — verbal confidence of "
        "items that flip correct→incorrect vs items that stay correct (two-sample Student t-test). "
        "C4: on the same 60 items, does the misleading passage or the explicit injection move more "
        "answers onto k? (McNemar; the overlap counts are descriptive).")
    xrows, fig_c = [], {}
    for m in models:
        c = get(df, m, "clean").loc[lambda d: d.index <= SUBSETS["stress"][1]]
        x = get(df, m, "misleading")
        if len(x):
            cc, xx = paired(c, x)
            row = _auc_row(m, "C1 clean uncertainty → misleading adoption", 1 - cc.tok_conf, xx.picked_type1)
            (au, lo, hi), _ = auroc_ci(1 - cc.tok_conf, xx.picked_type1)
            row["H2"] = "supported" if lo > 0.5 else "not supported"
            xrows.append(row)
            fig_c[m] = (1 - cc.tok_conf, xx.picked_type1)
            # Sensitivity: drop items whose CLEAN answer already was k, so a positive means the
            # misleading context newly moved the model onto k (not a pre-existing preference).
            new = ~cc.picked_type1.astype(bool)
            xrows.append(_auc_row(m, "C1b sensitivity: newly adopted (clean answer ≠ k)",
                                  1 - cc.tok_conf[new], xx.picked_type1[new]))
            flip = cc.correct & ~xx.correct
            stay = cc.correct & xx.correct
            for name, conf in (("C3 verbal conf: C→I vs stayed-correct (misleading)", xx.verbal_confidence),
                               ("C3b control: same groups, CLEAN verbal conf", cc.verbal_confidence)):
                xrows.append(dict(model=m, analysis=name, n=int((flip | stay).sum()), positives=int(flip.sum()),
                                  statistic=f"mean {conf[flip].mean():.1f} vs {conf[stay].mean():.1f}",
                                  p=f"{ttest_ind_p(conf[flip], conf[stay]):.4f}"))
        x = get(df, m, "injection")
        if len(x):
            cc, xx = paired(c, x)
            xrows.append(_auc_row(m, "C2 clean uncertainty → injection answer-following",
                                  1 - cc.tok_conf, xx.picked_type1))
            new = ~cc.picked_type1.astype(bool)
            xrows.append(_auc_row(m, "C2b sensitivity: newly followed (clean answer ≠ k)",
                                  1 - cc.tok_conf[new], xx.picked_type1[new]))
        a, b = paired(get(df, m, "misleading"), get(df, m, "injection"))
        if len(a):
            x1, x2 = a.picked_type1.astype(bool).values, b.picked_type1.astype(bool).values
            n10, n01, p = mcnemar_test(x1, x2)
            xrows.append(dict(model=m, analysis="C4 chooses k: misleading passage vs injection (McNemar)",
                              n=len(a), positives=f"{int(x1.sum())} vs {int(x2.sum())}",
                              statistic=f"both {int((x1 & x2).sum())}, misleading only {n10}, "
                                        f"injection only {n01}, neither {int((~x1 & ~x2).sum())}",
                              p=f"{p:.4f}"))
    for r in xrows:
        r.setdefault("H2", "-")
    R.table("C_cross_dimension", xrows)
    R.p("p: z-test (AUC rows), two-sample Student t-test (C3, C3b) or McNemar (C4), uncorrected for "
        "the number of tests. Rows marked b are sensitivity/control analyses: C1b/C2b drop items the "
        "model already answered k on the clean prompt; C3b repeats C3 with the CLEAN verbal confidence "
        "of the same items, so a C3 gap that is also present in C3b reflects item difficulty rather "
        "than misinformation-induced overconfidence.")
    R.p("Limitation: n = 60 items per model; few positive events make AUC intervals wide. Results are per "
        "model (not pooled) because the two models' confidence scales are not comparable.")
    if fig_c:
        plt = _plt()
        fig, ax = plt.subplots(figsize=(5, 3))
        for i, (m, (u, y)) in enumerate(fig_c.items()):
            for j, lab in enumerate([False, True]):
                vals = u[y == lab].dropna().values
                pos = i * 2.5 + j
                if len(vals):
                    ax.boxplot(vals, positions=[pos], widths=0.6, patch_artist=True,
                               boxprops=dict(facecolor=COLORS[m] if lab else "white", edgecolor=COLORS[m]),
                               medianprops=dict(color=COLORS["ink"]), showfliers=False)
                    ax.scatter(np.full(len(vals), pos) + np.random.default_rng(SEED).uniform(-.15, .15, len(vals)),
                               vals, s=8, color=COLORS["ink"], alpha=0.5, zorder=3)
        ax.set_xticks([0, 1, 2.5, 3.5][:2 * len(fig_c)],
                      [f"{m}\nnot adopted" if j == 0 else f"{m}\nadopted" for m in fig_c for j in (0, 1)])
        ax.set_ylabel("clean uncertainty (1 − token conf)")
        ax.set_title("C1: uncertainty vs misinformation adoption")
        fig.tight_layout()
        fig.savefig(out / "figures" / "C_cross.png")
        plt.close(fig)


__all__ = [n for n in dir() if not n.startswith("__")]  # so the next step can `from ... import *`


if __name__ == "__main__":
    step_main("step7_cross_dimension", analyze_cross_dimension, [], description=__doc__)