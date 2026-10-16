"""
EXTRA -- EXPLORATORY: DOES REASONING BEFORE ANSWERING CHANGE THE RESULTS?
=======================================================================
Not part of the fixed benchmark. The main protocol (steps 1-9) stays answer-first; this file
adds a separate, clearly labelled comparison. The hypothesis was formulated AFTER seeing the
low baseline accuracy, and the paper must say so.

H3 (exploratory)
  Mechanism: in the answer-first format the model commits to a letter in its first output
  tokens, before writing anything about the vignette. With a reasoning field first, the answer
  can depend on that reasoning (each generated token is context for the next).
  Supported if Core accuracy rises with reasoning-first (McNemar chi-square p < 0.05 AND more
  incorrect->correct than correct->incorrect). Not supported otherwise.
  Misleading context: no directional prediction -- reasoning could expose the conflict with the
  vignette, or elaborate on the injected claim. The change in adoption is reported with McNemar.

What this file adds
  * A reasoning-first system prompt: {"reasoning", "answer", "confidence", "evidence"}.
  * Two conditions with the SAME question text as their answer-first counterparts:
        reason_clean       Core set (rows 0-199)  vs  clean        (step 2)
        reason_misleading  Stress set (rows 0-59) vs  misleading   (step 3)
  * max_new_tokens = 512 for these conditions only (outputs cut off at 512 count as invalid).
  * Token confidence read AT THE GENERATION STEP THAT EMITS THE ANSWER LETTER: a logits processor
    records the option-letter logits at every step, and the step is located as the first letter
    token generated right after '"answer": "'. (A fixed forced prefix cannot work once reasoning
    comes first.) If the letter is merged with other characters into one token, the step is not
    found and token confidence is left empty -- the rate is reported.
  * A paired comparison, a LaTeX table for the paper (results/tables/extra_reasoning.tex) and a
    figure (results/figures/X_reasoning.png).

Run it (after steps 2 and 3, which provide the answer-first baselines)
    python extra_reasoning.py --show-prompt
    python extra_reasoning.py --model llama qwen
    python extra_reasoning.py                      # re-analyse only

Cost: about 260 generations per model at up to 512 new tokens.
"""
from __future__ import annotations

import copy

from step3_hallucination import *

REASONING_MAX_NEW_TOKENS = 512
LETTERS = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
_ANSWER_KEY_RE = re.compile(r'"answer"\s*:\s*"\s*$')
_MENTIONS_UNVERIFIED = re.compile(r"unverified|not verified|cannot be verified|unsupported|"
                                  r"additional context|provided context|the context (?:states|claims|suggests)", re.I)

SYSTEM_REASONING = (
    "You are a careful clinical reasoning assistant. You will be given one multiple-choice "
    "question about mental health or psychiatry. Choose exactly one option.\n"
    "First reason through the case step by step, then answer.\n"
    "Respond with ONLY a single JSON object and nothing else, in exactly this format:\n"
    '{"reasoning": "<your step-by-step analysis of the case and the options, at most 150 words>", '
    '"answer": "<option letter>", "confidence": <integer from 0 to 100>, '
    '"evidence": "<one or two sentences citing the facts that support your answer>"}\n'
    '"confidence" is how likely you think it is that your answer is correct, as a percentage.'
)

PAIRS = {"reason_clean": "clean", "reason_misleading": "misleading"}   # reasoning-first -> answer-first

register_condition("reason_clean", subset="core", system=lambda row: SYSTEM_REASONING)
register_condition("reason_misleading", question=CONDITIONS["misleading"]["question"],
                   system=lambda row: SYSTEM_REASONING)
REASON_CONDITIONS = list(PAIRS)


# =============================================================================
# GENERATION WITH ANSWER-STEP LETTER LOGITS
# =============================================================================
def make_letter_recorder(letter_ids):
    """Logits processor that records, at every generation step, the logits of the 26 letter
    tokens and the log-sum-exp over the full vocabulary. It returns the scores unchanged, so
    greedy decoding is unaffected. Memory: 27 floats per item per step."""
    import torch
    from transformers import LogitsProcessor

    class LetterRecorder(LogitsProcessor):
        def __init__(self):
            self.ids = torch.tensor(letter_ids)
            self.steps = []

        def __call__(self, input_ids, scores):
            s = scores.float()
            self.steps.append((s[:, self.ids.to(s.device)].cpu(), torch.logsumexp(s, -1).cpu()))
            return scores

    return LetterRecorder()


def find_answer_step(tok, gen_ids, letter_id_set):
    """Index of the LAST generated letter token that directly follows '"answer": "'.
    The last one, because parse_output keeps the last value of a repeated JSON key; using the
    first would read the token confidence of an answer the parser discarded."""
    found = None
    for j, t in enumerate(gen_ids):
        if t in letter_id_set:
            prefix = tok.decode(gen_ids[:j], skip_special_tokens=True, clean_up_tokenization_spaces=False)
            if _ANSWER_KEY_RE.search(prefix):
                found = j
    return found


def generate_with_answer_logits(runner, texts, max_new_tokens=REASONING_MAX_NEW_TOKENS):
    """Greedy generation (same settings as the main runs except max_new_tokens) that also returns,
    per item, the generation step of the answer letter and the recorded letter logits there."""
    from transformers import LogitsProcessorList
    torch = runner.torch
    letter_ids = [runner.letter_ids[L] for L in LETTERS]
    rec = make_letter_recorder(letter_ids)
    gc = copy.deepcopy(runner.gen_config)
    gc.max_new_tokens = max_new_tokens
    enc = runner._enc(texts)
    with torch.no_grad():
        out = runner.model.generate(**enc, generation_config=gc, logits_processor=LogitsProcessorList([rec]))
    new = out[:, enc["input_ids"].shape[1]:].tolist()
    eos = gc.eos_token_id
    eos = set(eos if isinstance(eos, list) else [eos])
    letter_set = set(letter_ids)
    results = []
    for i, row_ids in enumerate(new):
        n = next((j for j, t in enumerate(row_ids) if t in eos), len(row_ids))
        ids = row_ids[:n]
        text = runner.tok.decode(ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)
        step = find_answer_step(runner.tok, ids, letter_set)
        letter_logits, lse = (None, None)
        if step is not None and step < len(rec.steps):
            letter_logits = rec.steps[step][0][i].tolist()
            lse = float(rec.steps[step][1][i])
        results.append(dict(text=text, n_new=n, n_in=int(enc["attention_mask"][i].sum()),
                            answer_step=step, letter_logits=letter_logits, lse=lse,
                            step_letter=runner.tok.decode([ids[step]]) if step is not None else None))
    return results


def option_probs_from_logits(letter_logits, lse, keys):
    """Renormalise over the item's option letters (same definition as the forced-prefix measure)."""
    if letter_logits is None:
        return None, None
    l = np.array([letter_logits[LETTERS.index(k)] for k in keys], dtype=float)
    p = np.exp(l - l.max())
    p /= p.sum()
    mass = float(np.exp(l - lse).sum())
    return {k: round(float(x), 6) for k, x in zip(keys, p)}, round(mass, 6)


def _run_reason_batch(runner, batch, condition, run_id, allow_split=True):
    torch = runner.torch
    msgs = [build_messages(r, condition) for r in batch]
    texts = [runner.render(m) for m in msgs]
    t0 = time.time()
    try:
        res = generate_with_answer_logits(runner, texts)
        err = None
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        if allow_split and len(batch) > 1:
            log.warning("OOM at batch %d -> per-item fallback", len(batch))
            return [x for r in batch for x in _run_reason_batch(runner, [r], condition, run_id, False)]
        res, err = [dict(text=None, n_new=None, n_in=None, answer_step=None, letter_logits=None,
                         lse=None, step_letter=None)] * len(batch), "CUDA OOM"
    except CODE_ERRORS:
        raise  # a bug in our code, not a model failure: stop instead of saving it as a failed generation
    except Exception as e:  # genuine generation failure: recorded, never dropped
        log.exception("generation failed")
        res, err = [dict(text=None, n_new=None, n_in=None, answer_step=None, letter_logits=None,
                         lse=None, step_letter=None)] * len(batch), repr(e)
    dt = (time.time() - t0) / len(batch)
    gen_settings = dict(GENERATION, max_new_tokens=REASONING_MAX_NEW_TOKENS)
    recs = []
    for r, m, x in zip(batch, msgs, res):
        p, mass = option_probs_from_logits(x["letter_logits"], x["lse"], list(r["options"]))
        recs.append(dict(
            run_id=run_id, timestamp=datetime.now(timezone.utc).isoformat(), model=runner.key,
            hf_id=runner.hf_id, model_revision=runner.revision, dtype=INFERENCE["dtype"],
            quantization=runner.quant, condition=condition, subset=subset_for(condition),
            prompt_version=PROMPT_VERSION, prompt_fingerprint=prompt_fingerprint(condition),
            row_index=r["row_index"], dataset_id=r["id"], gold=r["answer"],
            type1_injection_key=r["type1_injection_key"], option_keys=list(r["options"]),
            canary=None, system=m[0]["content"], user=m[1]["content"], raw_output=x["text"],
            n_input_tokens=x["n_in"], n_new_tokens=x["n_new"], latency_s=round(dt, 3),
            option_probs=p, option_letter_mass=mass, answer_step=x["answer_step"],
            answer_step_token=x["step_letter"], confidence_method="answer-step logits during generation",
            generation_settings=gen_settings, batch_size=len(batch), seed=SEED, error=err))
    return recs


def run_reason_condition(runner, rows, condition, out, bs, run_id):
    """Same resume logic as run_condition in step 2 (half-written lines removed, --retry-errors)."""
    path = out / "raw" / runner.key / f"{condition}.jsonl"
    done = _load_done(path)
    todo = [r for r in subset(rows, subset_for(condition)) if r["row_index"] not in done]
    log.info("%s/%s: %d done, %d to run", runner.key, condition, len(done), len(todo))
    with open(path, "a", encoding="utf-8") as f:
        for b in range(0, len(todo), bs):
            for rec in _run_reason_batch(runner, todo[b:b + bs], condition, run_id):
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()


# =============================================================================
# ANALYSIS
# =============================================================================
def _reasoning_text(raw):
    if not isinstance(raw, str):
        return ""
    m = re.search(r'"reasoning"\s*:\s*"((?:[^"\\]|\\.)*)', raw, re.S)
    return m.group(1) if m else ""


def _tex(s):
    return str(s).replace("%", r"\%").replace("&", r"\&").replace("_", r"\_").replace("→", r"$\rightarrow$")


def analyze_reasoning(df, rows, R):
    out = R.out
    models = models_in(df)
    R.h("EXTRA. Reasoning before answering (exploratory, H3)")
    R.p("Exploratory comparison, formulated after observing the baseline; not part of the fixed "
        "benchmark. Same items and question text; only the output format differs (reasoning field "
        f"first, max {REASONING_MAX_NEW_TOKENS} new tokens). Token confidence is read from the logits "
        "at the generation step that emits the answer letter. Tests: McNemar chi-square on the C→I / I→C "
        "counts describe how many items changed.")
    rows_md, tex, fig = [], {}, {}
    for m in models:
        af_c, rf_c = paired(get(df, m, "clean"), get(df, m, "reason_clean"))
        if not len(rf_c):
            continue
        n = len(rf_c)
        n10, n01, p = mcnemar_test(af_c.correct, rf_c.correct)   # n10: C->I, n01: I->C
        verdict = "supported" if (p < 0.05 and n01 > n10) else "not supported"
        trunc = (rf_c.n_new_tokens >= REASONING_MAX_NEW_TOKENS).fillna(False)
        step_found = rf_c.option_probs.notna()
        agree = (rf_c.parsed_answer == rf_c.tok_pred)[step_found & rf_c.valid]
        core = dict(
            model=m, n=n,
            acc_answer_first=fmt_rate(int(af_c.correct.sum()), n),
            acc_reasoning_first=fmt_rate(int(rf_c.correct.sum()), n),
            mcnemar_CtoI_ItoC_p=f"{n10}/{n01}, p={p:.4f}", H3=verdict,
            valid_rf=fmt_rate(int(rf_c.valid.sum()), n), truncated_rf=f"{int(trunc.sum())}/{n}",
            answer_step_found=f"{int(step_found.sum())}/{n}",
            duplicate_keys_rf=f"{int(rf_c.duplicate_keys.notna().sum())}/{n}" if "duplicate_keys" in rf_c else "n/a",
            conflicting_answers_rf=(f"{int(rf_c.duplicate_keys.fillna('').str.contains('CONFLICTING').sum())}/{n}"
                                    if "duplicate_keys" in rf_c else "n/a"),
            gen_vs_token_agree=f"{agree.mean():.3f}" if len(agree) else "n/a",
            new_tokens_af_rf=f"{af_c.n_new_tokens.mean():.0f} → {rf_c.n_new_tokens.mean():.0f}",
            latency_af_rf=f"{af_c.latency_s.mean():.2f} → {rf_c.latency_s.mean():.2f}",
            verbal_conf_af_rf=f"{af_c.verbal_confidence.mean():.1f} → {rf_c.verbal_confidence.mean():.1f}",
            calib_gap_verbal_af_rf=f"{calib_gap(af_c.vconf01, af_c.correct):+.3f} → {calib_gap(rf_c.vconf01, rf_c.correct):+.3f}",
            AUC_verbal_af_rf=f"{auroc(af_c.vconf01, af_c.correct)[0]:.3f} → {auroc(rf_c.vconf01, rf_c.correct)[0]:.3f}")
        t = dict(acc=(f"{100 * af_c.correct.mean():.1f} → {100 * rf_c.correct.mean():.1f}"),
                 mcn=f"{n10}/{n01}, {p:.3f}", verdict=verdict,
                 valid=f"{100 * rf_c.valid.mean():.1f}", trunc=f"{int(trunc.sum())}/{n}",
                 toks=core["new_tokens_af_rf"], conf=core["verbal_conf_af_rf"], gap=core["calib_gap_verbal_af_rf"])
        fig[m] = dict(acc=(zci(int(af_c.correct.sum()), n), zci(int(rf_c.correct.sum()), n)))
        af_m, rf_m = paired(get(df, m, "misleading"), get(df, m, "reason_misleading"))
        if len(rf_m):
            k = len(rf_m)
            a10, a01, pa = mcnemar_test(af_m.picked_type1, rf_m.picked_type1)
            rc0, rm0 = paired(get(df, m, "reason_clean").loc[lambda d: d.index <= SUBSETS["stress"][1]], rf_m)
            d10, d01, pd_ = mcnemar_test(rc0.correct, rm0.correct)
            mention = rf_m.raw_output.map(lambda s: bool(_MENTIONS_UNVERIFIED.search(_reasoning_text(s))))
            core.update(
                adoption_af=fmt_rate(int(af_m.picked_type1.sum()), k),
                adoption_rf=fmt_rate(int(rf_m.picked_type1.sum()), k),
                adoption_mcnemar=f"{a10}/{a01}, p={pa:.4f}",
                acc_misleading_af_rf=f"{af_m.correct.mean():.3f} → {rf_m.correct.mean():.3f}",
                rf_acc_clean_to_misleading=f"{rc0.correct.mean():.3f} → {rm0.correct.mean():.3f} "
                                           f"(McNemar p={pd_:.4f}; C→I/I→C {d10}/{d01})",
                rf_reasoning_flags_unverified=fmt_rate(int(mention.sum()), k),
                rf_evidence_reuses_injection=fmt_rate(int(rf_m.evid_relies_on_injection.sum()), k))
            t.update(adopt=f"{100 * af_m.picked_type1.mean():.1f} → {100 * rf_m.picked_type1.mean():.1f}",
                     amcn=f"{a10}/{a01}, {pa:.3f}",
                     macc=f"{100 * af_m.correct.mean():.1f} → {100 * rf_m.correct.mean():.1f}",
                     flag=f"{100 * mention.mean():.1f}")
            fig[m]["adopt"] = (zci(int(af_m.picked_type1.sum()), k), zci(int(rf_m.picked_type1.sum()), k))
        rows_md.append(core)
        tex[m] = t
    R.table("X_reasoning", rows_md)

    # ---- LaTeX table for the paper (numbers come only from the saved results)
    if tex:
        ms = list(tex)
        head = " & ".join(rf"\textsc{{{m.capitalize()}}}" for m in ms)
        lines = [
            ("Core accuracy, answer-first $\\rightarrow$ reasoning-first (\\%)", "acc"),
            ("\\quad C$\\rightarrow$I / I$\\rightarrow$C, McNemar $p$", "mcn"),
            ("\\quad H3 verdict", "verdict"),
            ("Valid outputs, reasoning-first (\\%)", "valid"),
            ("Cut off at 512 tokens", "trunc"),
            ("New tokens per item", "toks"),
            ("Mean verbal confidence", "conf"),
            ("Calibration gap (verbal conf.\\ $-$ accuracy)", "gap"),
            ("Misleading: adoption of $k$ (\\%)", "adopt"),
            ("\\quad changes / McNemar $p$ (adoption)", "amcn"),
            ("Misleading: accuracy (\\%)", "macc"),
            ("Reasoning flags unverified context (\\%)", "flag"),
        ]
        body = "\n".join(f"{label} & " + " & ".join(_tex(tex[m].get(key, "--")) for m in ms) + r" \\"
                         for label, key in lines)
        cols = "l" + "c" * len(ms)
        (out / "tables" / "extra_reasoning.tex").write_text(
            "% Auto-generated by extra_reasoning.py -- do not edit by hand.\n"
            "\\begin{table}[t]\n\\centering\n\\small\n\\resizebox{\\columnwidth}{!}{%\n"
            f"\\begin{{tabular}}{{{cols}}}\n\\toprule\n & {head} \\\\\n\\midrule\n{body}\n"
            "\\bottomrule\n\\end{tabular}}\n"
            "\\caption{Exploratory comparison of answer-first and reasoning-first output formats on the "
            "same items (Core set, $n=200$; misleading condition, $n=60$). McNemar chi-square tests on the item changes C$\\rightarrow$I/I$\\rightarrow$C. "
            "Values are answer-first $\\rightarrow$ reasoning-first where two are shown.}\n"
            "\\label{tab:extra}\n\\end{table}\n", encoding="utf-8")
        R.p("LaTeX table for the paper: `tables/extra_reasoning.tex`.")

    # ---- figure
    if fig:
        plt = _plt()
        groups = [("acc", "Core accuracy"), ("adopt", "Misleading: adoption of k")]
        fig_, axes = plt.subplots(1, 2, figsize=(8, 3))
        for ax, (key, title) in zip(axes, groups):
            for i, m in enumerate(fig):
                if key not in fig[m]:
                    continue
                for j, (label, hatch) in enumerate([("answer-first", None), ("reasoning-first", "///")]):
                    est, lo, hi = fig[m][key][j]
                    x = i + (j - 0.5) * 0.38
                    ax.bar(x, est, 0.34, color=COLORS[m] if j == 0 else "white", edgecolor=COLORS[m],
                           hatch=hatch, lw=1.5,
                           yerr=[[max(0, est - lo)], [max(0, hi - est)]], capsize=2,
                           error_kw=dict(ecolor=COLORS["ink"], lw=0.8),
                           label=label if i == 0 else None)
            ax.set_xticks(range(len(fig)), list(fig))
            ax.set(ylim=(0, 1), title=title, ylabel="rate (95% CI)")
        axes[0].legend(frameon=False, fontsize=8)
        fig_.tight_layout()
        fig_.savefig(out / "figures" / "X_reasoning.png")
        plt.close(fig_)


# =============================================================================
# RUN THIS STEP
# =============================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", nargs="*", default=[], choices=list(MODELS))
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--data-file", default=None)
    ap.add_argument("--load-in-4bit", action="store_true")
    ap.add_argument("--batch-size", type=int, default=INFERENCE["batch_size"])
    ap.add_argument("--skip-analysis", action="store_true")
    ap.add_argument("--show-prompt", action="store_true")
    ap.add_argument("--retry-errors", action="store_true",
                    help="re-generate items whose saved record has an error (newer record is kept)")
    a = ap.parse_args()
    import step2_baseline
    step2_baseline.RETRY_ERRORS = a.retry_errors
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)
    out = Path(a.out)
    if a.show_prompt:
        rows = load_dataset(out, a.data_file)
        for c in REASON_CONDITIONS:
            msg = build_messages(rows[0], c)
            print(f"\n{'=' * 25} condition: {c} {'=' * 25}\n[SYSTEM]\n{msg[0]['content']}\n\n[USER]\n{msg[1]['content']}")
        return
    if a.model:
        rows = load_dataset(out, a.data_file)
        INFERENCE["batch_size"] = a.batch_size
        for key in a.model:
            runner = load_runner(out, key, a.load_in_4bit)
            run_id = uuid.uuid4().hex[:10]
            manifest(runner, out, run_id, REASON_CONDITIONS)
            for c in REASON_CONDITIONS:
                run_reason_condition(runner, rows, c, out, a.batch_size, run_id)
            free_runner(runner)
    if not a.skip_analysis:
        analyze_section(out, [analyze_reasoning], "extra_reasoning")


__all__ = [n for n in dir() if not n.startswith("__")]

if __name__ == "__main__":
    main()