"""
STEP 4 -- PART B.2: INTERPRETABILITY (Interp set, rows 0-39, clean prompts only)
=================================================================================
Identical protocol for both models:
  (a) Sentence OCCLUSION: remove one question sentence at a time; drop in log p(predicted option).
  (b) GRADIENT x INPUT on the input embeddings, summed per sentence.
  (c) FAITHFULNESS TEST WITH A CONTROL: delete the top-k attributed sentences vs k RANDOM sentences
      (5 seeded draws) vs the BOTTOM-k. A faithful attribution should hurt more than random
      (paired Student t-test on top - random).
  (d) LOGIT LENS: where the answer letter emerges across layers.
  (e) Does the model's written evidence cite the top-attributed sentence?
  Raw: results/raw/<model>/interp.jsonl

Run (after steps 2 and 3)
    python step4_interpretability.py --model llama qwen
    python step4_interpretability.py                     # analysis only (CPU is fine)
Resumable: finished items are skipped.

Outputs: results/summary_step4_interpretability.md, tables/B2_*.csv, tables/B2_interp_cases.md,
         figures/B2_logit_lens.png

Next: step5_fairness.py
"""
from __future__ import annotations

from step3_hallucination import *

INTERP = dict(top_frac=0.2, random_controls=5)   # delete top 20% of sentences (at least 1); 5 random-deletion controls

_SPLIT = re.compile(r'[.!?]["\')\]]*(\s+)(?=[A-Z0-9"(\[])')


def split_sentences(q: str):
    spans, start = [], 0
    for m in _SPLIT.finditer(q):
        spans.append((start, m.start(1)))
        start = m.end()
    spans.append((start, len(q)))
    return [(s, e) for s, e in spans if q[s:e].strip()]


def _logp_of(runner: Runner, rows_q, pred_letter, keys, condition="clean", bs=8):
    """log p(pred | prompt) over option letters, for a list of (row, question_text)."""
    vals = []
    for b in range(0, len(rows_q), bs):
        chunk = rows_q[b:b + bs]
        texts = [runner.render(build_messages(r, condition, q)) + ANSWER_PREFIX for r, q in chunk]
        for p, _ in runner.option_probs(texts, [keys] * len(chunk)):
            vals.append((math.log(max(p[pred_letter], 1e-12)), max(p, key=p.get)))
    return vals


def grad_x_input(runner: Runner, row, pred, keys, spans):
    torch = runner.torch
    text = runner.render(build_messages(row, "clean")) + ANSWER_PREFIX
    q = row["question"]
    q0 = text.find(q)
    if q0 < 0:
        return None
    enc = runner.tok(text, return_tensors="pt", add_special_tokens=False, return_offsets_mapping=True)
    offsets = enc.pop("offset_mapping")[0].tolist()
    ids = enc["input_ids"].to(runner.device)
    emb = runner.model.get_input_embeddings()(ids).detach().requires_grad_(True)
    with torch.enable_grad():
        out = runner.model.model(inputs_embeds=emb, attention_mask=enc["attention_mask"].to(runner.device))
        logits = runner.model.lm_head(out.last_hidden_state[:, -1]).float()[0]
        l = logits[[runner.letter_ids[k] for k in keys]]
        lp = torch.log_softmax(l, -1)[keys.index(pred)]
        lp.backward()
    tok_attr = (emb.grad.float() * emb.float()).sum(-1)[0].tolist()
    scores = [0.0] * len(spans)
    for (a, b), s in zip(offsets, tok_attr):
        for i, (ss, ee) in enumerate(spans):
            if q0 + ss <= a < q0 + ee:
                scores[i] += s
                break
    del emb, out
    torch.cuda.empty_cache()
    return scores


def logit_lens(runner: Runner, row, pred, keys):
    torch = runner.torch
    text = runner.render(build_messages(row, "clean")) + ANSWER_PREFIX
    _, hs = runner.last_logits([text], hidden_states=True)
    ids = [runner.letter_ids[k] for k in keys]
    curve, argmaxes = [], []
    with torch.no_grad():
        for li, h in enumerate(hs):
            v = h[:, -1]
            if li < len(hs) - 1:  # HF already applies the final norm to the last element
                v = runner.model.model.norm(v)
            p = torch.softmax(runner.model.lm_head(v).float()[0, ids], -1)
            curve.append(round(float(p[keys.index(pred)]), 5))
            argmaxes.append(keys[int(p.argmax())])
    emerge = next((i for i in range(len(argmaxes)) if all(a == pred for a in argmaxes[i:])), None)
    return curve, emerge


def run_interp(runner: Runner, rows, out: Path, clean_records: dict):
    path = out / "raw" / runner.key / "interp.jsonl"
    done = set()
    if path.exists():
        done = {json.loads(l)["row_index"] for l in path.read_text().splitlines() if l.strip()}
    rng_base = SEED
    with open(path, "a", encoding="utf-8") as f:
        for row in subset(rows, "interp"):
            if row["row_index"] in done:
                continue
            q, keys = row["question"], list(row["options"])
            spans = split_sentences(q)
            sents = [q[s:e] for s, e in spans]
            n = len(sents)
            full_p, _ = runner.option_probs(
                [runner.render(build_messages(row, "clean")) + ANSWER_PREFIX], [keys])[0]
            pred = max(full_p, key=full_p.get)
            lp_full = math.log(max(full_p[pred], 1e-12))
            rec = dict(model=runner.key, model_revision=runner.revision, row_index=row["row_index"],
                       dataset_id=row["id"], gold=row["answer"], pred=pred, p_pred=full_p[pred],
                       option_probs=full_p, n_sentences=n, sentences=sents)
            # (a) occlusion
            occl = _logp_of(runner, [(row, " ".join(sents[:i] + sents[i + 1:])) for i in range(n)], pred, keys) \
                if n > 1 else []
            rec["occlusion"] = [round(lp_full - v, 5) for v, _ in occl]
            # (b) gradient x input
            try:
                g = grad_x_input(runner, row, pred, keys, spans)
            except Exception as e:  # recorded
                g, rec["grad_error"] = None, repr(e)
            rec["gradxinput"] = [round(x, 6) for x in g] if g else None
            # (c) deletion faithfulness test with controls
            k = max(1, round(INTERP["top_frac"] * n))
            rec["k_deleted"] = k
            rec["deletion"] = {}
            if n > 1:
                rng = np.random.default_rng(rng_base + row["row_index"])
                rand_sets = [sorted(rng.choice(n, size=k, replace=False).tolist())
                             for _ in range(INTERP["random_controls"])]
                for method in ("occlusion", "gradxinput"):
                    sc = rec.get(method)
                    if not sc:
                        continue
                    order = np.argsort(-np.asarray(sc), kind="stable")
                    sets = {"top": sorted(order[:k].tolist()), "bottom": sorted(order[-k:].tolist())}
                    for j, rs in enumerate(rand_sets):
                        sets[f"random{j}"] = rs
                    qs = [(row, " ".join(s for i, s in enumerate(sents) if i not in set(v))) for v in sets.values()]
                    vals = _logp_of(runner, qs, pred, keys)
                    res = {}
                    for name, (lpv, am) in zip(sets, vals):
                        res[name] = dict(removed=sets[name], drop=round(lp_full - lpv, 5), flipped=am != pred)
                    rd = [res[f"random{j}"] for j in range(len(rand_sets))]
                    res["random_mean_drop"] = float(np.mean([r["drop"] for r in rd]))
                    res["random_flip_rate"] = float(np.mean([r["flipped"] for r in rd]))
                    rec["deletion"][method] = res
            # (d) logit lens
            try:
                rec["lens_curve"], rec["lens_emergence_layer"] = logit_lens(runner, row, pred, keys)
            except Exception as e:
                rec["lens_error"] = repr(e)
            # (e) evidence vs attribution
            cr = clean_records.get(row["row_index"])
            ev = parse_output(cr["raw_output"], keys)["evidence"] if cr and cr.get("raw_output") else None
            rec["evidence"] = ev
            if ev and n > 1:
                et = content_tokens(ev)
                overlap = [len(et & content_tokens(s)) for s in sents]
                rec["evidence_overlap"] = overlap
                rec["evidence_cited_sentence"] = int(np.argmax(overlap)) if max(overlap) > 0 else None
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            log.info("interp %s row %d (n=%d)", runner.key, row["row_index"], n)


# =============================================================================
# PART B.2 ANALYSIS
# =============================================================================
def _analyze_required(df, rows, R):
    out = R.out
    models = models_in(df)
    R.h("B2. Interpretability (Interp set, rows 0–39, clean)")
    R.p("Methods: sentence occlusion and gradient×input attribution on log p(predicted option) at the "
        "forced answer position; **faithfulness test** = delete the top-k attributed sentences "
        f"(k = max(1, round({INTERP['top_frac']}·n))) vs **controls**: k random sentences "
        f"({INTERP['random_controls']} seeded draws) and the bottom-k. Faithful attribution ⇒ top-k "
        "deletion drops log p(pred) more than random (paired Student t-test) and flips the answer more often. "
        "Occlusion's top-1 is partly circular when k=1 (it was measured by deletion); gradient×input "
        "is the non-circular test. Neither establishes the mechanism; deletions create off-distribution text.")
    irows, lens, icase = [], {}, []
    for m in models:
        f = out / "raw" / m / "interp.jsonl"
        if not f.exists():
            continue
        I = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        for method in ("occlusion", "gradxinput"):
            D = [r for r in I if method in r.get("deletion", {})]
            if not D:
                continue
            top = np.array([r["deletion"][method]["top"]["drop"] for r in D])
            rnd = np.array([r["deletion"][method]["random_mean_drop"] for r in D])
            bot = np.array([r["deletion"][method]["bottom"]["drop"] for r in D])
            irows.append(dict(
                model=m, method=method, n_items=len(D),
                drop_top=fmt_ci(mean_ci(top)), drop_random=fmt_ci(mean_ci(rnd)), drop_bottom=fmt_ci(mean_ci(bot)),
                top_minus_random=fmt_ci(mean_ci(top - rnd)),
                paired_t_p_top_vs_random=f"{ttest_p(top - rnd):.4f}",
                frac_items_top_gt_random=f"{(top > rnd).mean():.3f}",
                flip_top=f"{np.mean([r['deletion'][method]['top']['flipped'] for r in D]):.3f}",
                flip_random=f"{np.mean([r['deletion'][method]['random_flip_rate'] for r in D]):.3f}",
                flip_bottom=f"{np.mean([r['deletion'][method]['bottom']['flipped'] for r in D]):.3f}"))
        # agreement between methods, and between attribution and evidence
        from scipy.stats import pearsonr
        agree, ev_hit, ev_chance, ev_pct = [], [], [], []
        for r in I:
            o, g = r.get("occlusion"), r.get("gradxinput")
            if o and g and len(o) > 2 and np.std(o) > 0 and np.std(g) > 0:
                agree.append(pearsonr(o, g)[0])
            cs = r.get("evidence_cited_sentence")
            if cs is not None and o:
                ranks = np.argsort(np.argsort(-np.asarray(o), kind="stable"), kind="stable")
                ev_hit.append(int(ranks[cs] == 0))
                ev_chance.append(1 / len(o))
                ev_pct.append(1 - ranks[cs] / max(1, len(o) - 1))
        irows.append(dict(model=m, method="occlusion vs grad×input", n_items=len(agree),
                          drop_top=f"mean Pearson r = {np.mean(agree):.3f}" if agree else "n/a"))
        irows.append(dict(model=m, method="evidence-cited sentence = top occlusion sentence", n_items=len(ev_hit),
                          drop_top=f"{np.mean(ev_hit):.3f} (chance {np.mean(ev_chance):.3f}); "
                                   f"mean percentile rank of cited sentence {np.mean(ev_pct):.3f} (chance 0.5)"
                          if ev_hit else "n/a"))
        curves = [r["lens_curve"] for r in I if r.get("lens_curve")]
        if curves:
            L = min(map(len, curves))
            lens[m] = np.array([c[:L] for c in curves])
            em = [r["lens_emergence_layer"] for r in I if r.get("lens_emergence_layer") is not None]
            irows.append(dict(model=m, method="logit lens", n_items=len(curves),
                              drop_top=f"answer stably emerges at layer {np.median(em):.0f} (median) of {L - 1}"))
        # informative cases
        D = [r for r in I if "gradxinput" in r.get("deletion", {}) or "occlusion" in r.get("deletion", {})]
        def gap(r, meth="occlusion"):
            d = r["deletion"].get(meth)
            return d["top"]["drop"] - d["random_mean_drop"] if d else float("nan")
        if D:
            best = max(D, key=lambda r: np.nan_to_num(gap(r), nan=-1e9))
            worst = min(D, key=lambda r: np.nan_to_num(gap(r, "gradxinput"), nan=1e9))
            mis_ev = [r for r in D if r.get("evidence_cited_sentence") is not None and r.get("occlusion")
                      and np.argsort(np.argsort(-np.asarray(r["occlusion"]), kind="stable"), kind="stable")[r["evidence_cited_sentence"]]
                      >= len(r["occlusion"]) // 2]
            for tag, r in [("useful: largest occlusion top−random gap", best),
                           ("misleading: grad×input top-k hurts less than random", worst)] + \
                          [("rationale vs attribution mismatch", mis_ev[0])] * bool(mis_ev):
                o = np.asarray(r.get("occlusion") or [0])
                ti = int(np.argmax(o))
                icase.append(f"### {m} — {tag} — row {r['row_index']} ({r['dataset_id']})\n"
                             f"gold={r['gold']}, pred={r['pred']} (p={r['p_pred']:.2f}), sentences={r['n_sentences']}, "
                             f"k={r['k_deleted']}\n\n- top occlusion sentence (Δlogp {o[ti]:.3f}): "
                             f"\"{r['sentences'][ti][:240]}\"\n"
                             f"- deletion: {json.dumps({k: {kk: (vv['drop'] if isinstance(vv, dict) else vv) for kk, vv in v.items() if kk in ('top', 'bottom', 'random_mean_drop')} for k, v in r['deletion'].items()})}\n"
                             f"- evidence: {r.get('evidence')}\n- evidence-cited sentence idx: "
                             f"{r.get('evidence_cited_sentence')}\n")
    R.table("B2_interpretability", irows)
    (out / "tables" / "B2_interp_cases.md").write_text("\n".join(icase) or "none", encoding="utf-8")
    R.p("Candidate case studies (≥3 per model) in `tables/B2_interp_cases.md` — read and annotate them in the report.")
    if lens:
        plt = _plt()
        fig, ax = plt.subplots(figsize=(5, 3))
        for m, arr in lens.items():
            mu = arr.mean(0)
            se = arr.std(0, ddof=1) / math.sqrt(len(arr))
            xs = np.arange(len(mu)) / (len(mu) - 1)
            ax.plot(xs, mu, color=COLORS[m], lw=2, label=f"{m} ({arr.shape[1] - 1} layers)")
            ax.fill_between(xs, mu - 1.96 * se, mu + 1.96 * se, color=COLORS[m], alpha=0.15, lw=0)
        ax.set(xlabel="relative depth", ylabel="p(final answer letter)", title="Logit lens, Interp set", ylim=(0, 1))
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(out / "figures" / "B2_logit_lens.png")
        plt.close(fig)


def _read_jsonl(p):
    out = []
    if p.exists():
        for l in p.read_text(encoding="utf-8").splitlines():
            if l.strip():
                try:
                    out.append(json.loads(l))
                except json.JSONDecodeError:
                    log.warning("%s: skipped an incomplete line (interrupted run)", p)
    return out


def analyze_interpretability(df, rows, R):
    _analyze_required(df, rows, R)


# =============================================================================
# RUN THIS STEP
# =============================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", nargs="*", default=[], choices=list(MODELS),
                    help="model(s) to run, one after the other (omit to only analyse saved results)")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--data-file", default=None)
    ap.add_argument("--load-in-4bit", action="store_true")
    ap.add_argument("--batch-size", type=int, default=INFERENCE["batch_size"])
    ap.add_argument("--skip-analysis", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)
    out = Path(a.out)
    if a.model:
        rows = load_dataset(out, a.data_file)
        INFERENCE["batch_size"] = a.batch_size
        for key in a.model:
            runner = load_runner(out, key, a.load_in_4bit)
            manifest(runner, out, uuid.uuid4().hex[:10], ["interp"])
            clean = {j["row_index"]: j for j in _read_jsonl(out / "raw" / key / "clean.jsonl")}
            if not clean:
                log.warning("clean.jsonl missing for %s: run step 2 first for the evidence check", key)
            run_interp(runner, rows, out, clean)
            free_runner(runner)
    if not a.skip_analysis:
        analyze_section(out, [analyze_interpretability], "step4_interpretability")


__all__ = [n for n in dir() if not n.startswith("__")]  # so the next step can `from ... import *`


if __name__ == "__main__":
    main()
