"""
STEP 1 -- SETUP: fixed configuration, dataset, and model loading
=================================================================
What this step teaches / does
  * Every value the brief fixes lives here: seed 42, the dataset + revision, the three
    row-index subsets, the two model ids, fp16 (NF4 only if needed), greedy decoding.
  * The dataset is downloaded at the exact revision, rows get a zero-based `row_index`
    in STORED order (never shuffled), and every row is validated. Problems are logged,
    never "fixed" -- the brief forbids editing examples.
  * `Runner` loads ONE model with its exact resolved commit, in float16 on a single GPU,
    with deterministic settings. It can (a) generate text and (b) read the next-token
    probabilities of the option letters -- the second is used from step 2 onwards as a
    model-internal confidence score.

Run it
    python step1_setup.py                       # dataset only (works on CPU)
    python step1_setup.py --model llama qwen    # also check HF access + load each model

What to check before moving on
  * 449 rows, subsets 200 / 60 / 40, and read the validation issues (if any).
  * Each model loads, the revision prints, and it answers the toy question.

Next: step2_baseline.py builds the real prompt and runs the 200-item baseline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import platform
import re
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

log = logging.getLogger("lcs2")

# ---------------------------------------------------------------- fixed by the brief
SEED = 42
DATASET = dict(
    repo_id="Johndfm/MedMisBench-MentalHealth",
    revision="9757095",
    filename="medmisbench_mentalhealth.jsonl",
    split="train",
    expected_rows=449,
)
SUBSETS = {"core": (0, 199), "stress": (0, 59), "interp": (0, 39)}
MODELS = {
    "llama": dict(
        hf_id="meta-llama/Llama-3.2-3B-Instruct",
        # Llama-3.x templates insert "Today Date: <today>" unless date_string is set;
        # pinning it keeps prompts byte-identical on every day the script is run.
        chat_kwargs={"date_string": "26 Jul 2024"},
    ),
    "qwen": dict(hf_id="Qwen/Qwen2.5-3B-Instruct", chat_kwargs={}),
}

# ---------------------------------------------------------------- inference setup
INFERENCE = dict(dtype="float16", load_in_4bit=False, batch_size=8)
NF4_CONFIG = dict(bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype="float16", bnb_4bit_use_double_quant=False)
GENERATION = dict(do_sample=False, num_beams=1, max_new_tokens=256, repetition_penalty=1.0)
PROMPT_VERSION = "v1"

# Results go to ./results relative to the working directory (on Kaggle the notebook runs from
# /kaggle/working, so they land in /kaggle/working/results). No absolute path is hard-coded.
DEFAULT_OUT = '/kaggle/working/results' if os.environ.get("KAGGLE_KERNEL_RUN_TYPE") else "results"



# =============================================================================
# DATASET
# =============================================================================
REQUIRED_FIELDS = ["id", "question", "answer", "options", "injections", "type1_injection_key"]


def resolve_dataset_revision(repo_id: str, short_rev: str) -> str:
    from huggingface_hub import HfApi
    for c in HfApi().list_repo_commits(repo_id, repo_type="dataset"):
        if c.commit_id.startswith(short_rev):
            return c.commit_id
    raise ValueError(f"revision {short_rev} not found for {repo_id}")


def validate_rows(rows: list[dict]) -> list[dict]:
    """Report problems; never modify rows."""
    issues = []
    for r in rows:
        miss = [f for f in REQUIRED_FIELDS if f not in r]
        if miss:
            issues.append({"row_index": r["row_index"], "issue": f"missing {miss}"})
            continue
        opts, k = r["options"], r["type1_injection_key"]
        if not isinstance(opts, dict) or not opts:
            issues.append({"row_index": r["row_index"], "issue": "options not a dict"})
            continue
        if r["answer"] not in opts:
            issues.append({"row_index": r["row_index"], "issue": f"gold {r['answer']!r} not in options"})
        if k not in opts:
            issues.append({"row_index": r["row_index"], "issue": f"type1 key {k!r} not in options"})
        if not isinstance(r["injections"], dict) or k not in r["injections"]:
            issues.append({"row_index": r["row_index"], "issue": f"injections lacks {k!r}"})
        if k == r["answer"]:
            issues.append({"row_index": r["row_index"], "issue": "type1 key == gold (note)"})
    return issues


def load_dataset(out: Path, data_file: str | None = None) -> list[dict]:
    if data_file:
        path, full_rev = Path(data_file), f"local-file:{DATASET['revision']}"
    else:
        from huggingface_hub import hf_hub_download
        full_rev = resolve_dataset_revision(DATASET["repo_id"], DATASET["revision"])
        path = Path(hf_hub_download(DATASET["repo_id"], DATASET["filename"],
                                    repo_type="dataset", revision=full_rev))
    raw, bad = [], []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f):
            if not line.strip():
                continue
            try:
                raw.append(json.loads(line))
            except json.JSONDecodeError as e:
                bad.append({"line": lineno, "error": str(e)})
    rows = [{"row_index": i, **r} for i, r in enumerate(raw)]  # stored order, zero-based
    issues = validate_rows(rows) + [{"row_index": None, "issue": f"malformed line {b}"} for b in bad]
    if len(rows) != DATASET["expected_rows"]:
        issues.append({"row_index": None, "issue": f"row count {len(rows)} != {DATASET['expected_rows']}"})
    for name, (lo, hi) in SUBSETS.items():
        n = sum(lo <= r["row_index"] <= hi for r in rows)
        assert n == hi - lo + 1, f"subset {name} has {n} rows"
    for i in issues:
        log.warning("dataset: %s", i)
    rawdir = out / "raw"
    rawdir.mkdir(parents=True, exist_ok=True)
    with open(rawdir / "dataset_rows.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (rawdir / "dataset_manifest.json").write_text(json.dumps({
        **DATASET, "resolved_revision": full_rev, "n_rows": len(rows), "subsets": SUBSETS,
        "sha256_file": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "issues": issues}, indent=2))
    return rows


def subset(rows: list[dict], name: str) -> list[dict]:
    lo, hi = SUBSETS[name]
    return [r for r in rows if lo <= r["row_index"] <= hi]


# =============================================================================
# MODEL
# =============================================================================
def set_determinism():
    import random
    import torch
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(SEED)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False


class Runner:
    def __init__(self, key: str, load_in_4bit: bool = False, revision: str | None = None):
        import torch
        import transformers
        from huggingface_hub import HfApi
        from transformers import AutoModelForCausalLM, AutoTokenizer, GenerationConfig

        set_determinism()
        self.torch = torch
        self.key, spec = key, MODELS[key]
        self.hf_id, self.chat_kwargs = spec["hf_id"], spec["chat_kwargs"]
        # exact commit: the one pinned by an earlier run (see load_runner), else the current head;
        # model_info also fails fast without access to the gated repo
        self.revision = revision or HfApi().model_info(self.hf_id).sha
        self.tok = AutoTokenizer.from_pretrained(self.hf_id, revision=self.revision)
        self.tok.padding_side = "left"
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        kw = dict(revision=self.revision, device_map={"": 0} if torch.cuda.is_available() else "cpu")
        dtype_kw = "dtype" if tuple(map(int, transformers.__version__.split(".")[:2])) >= (4, 56) else "torch_dtype"
        kw[dtype_kw] = torch.float16
        self.quant = None
        if load_in_4bit:
            from transformers import BitsAndBytesConfig
            self.quant = dict(NF4_CONFIG, load_in_4bit=True)
            kw["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=False)
        self.model = AutoModelForCausalLM.from_pretrained(self.hf_id, **kw).eval()
        for p in self.model.parameters():
            p.requires_grad_(False)
        self.device = next(self.model.parameters()).device
        eos = self.model.generation_config.eos_token_id
        self.gen_config = GenerationConfig(**GENERATION, pad_token_id=self.tok.pad_token_id, eos_token_id=eos,
                                           temperature=None, top_p=None, top_k=None)
        # The models ship sampling defaults (Llama: temperature 0.6, top_p 0.9) that newer
        # transformers merges into every generate() call. Decoding is greedy, so they are unused;
        # clear them so the merged config is exactly ours and the "not valid flags" warning goes away.
        for k in ("temperature", "top_p", "top_k"):
            setattr(self.model.generation_config, k, None)
        self.model.generation_config.do_sample = False
        self.letter_ids = {}
        for L in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            ids = self.tok.encode(L, add_special_tokens=False)
            assert len(ids) == 1, f"letter {L} is not a single token"
            self.letter_ids[L] = ids[0]
        self.versions = self._versions()

    def _versions(self):
        import accelerate
        import transformers
        from importlib import metadata
        v = dict(python=sys.version.split()[0], torch=self.torch.__version__, transformers=transformers.__version__,
                 accelerate=accelerate.__version__, numpy=np.__version__, platform=platform.platform(),
                 kaggle=bool(os.environ.get("KAGGLE_KERNEL_RUN_TYPE")))
        for pkg in ("huggingface_hub", "tokenizers", "safetensors", "bitsandbytes", "scipy", "pandas", "matplotlib"):
            try:
                v[pkg] = metadata.version(pkg)
            except metadata.PackageNotFoundError:
                pass
        if self.torch.cuda.is_available():
            v["gpu"] = self.torch.cuda.get_device_name(0)
            v["cuda"] = self.torch.version.cuda
        return v

    def render(self, messages, prefix: str = "") -> str:
        return self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                            **self.chat_kwargs) + prefix

    def _enc(self, texts):
        return self.tok(texts, return_tensors="pt", padding=True, add_special_tokens=False).to(self.device)

    def generate(self, texts):
        torch = self.torch
        enc = self._enc(texts)
        with torch.no_grad():
            out = self.model.generate(**enc, generation_config=self.gen_config)
        new = out[:, enc["input_ids"].shape[1]:]
        eos = self.gen_config.eos_token_id
        eos = set(eos if isinstance(eos, list) else [eos])
        n_new = []
        for row in new.tolist():
            n = len(row)
            for j, t in enumerate(row):
                if t in eos:
                    n = j
                    break
            n_new.append(n)
        n_in = enc["attention_mask"].sum(1).tolist()
        # clean_up_tokenization_spaces=False: keep the raw text exactly as generated (cleanup would
        # strip spaces before punctuation and differs across transformers versions).
        return self.tok.batch_decode(new, skip_special_tokens=True, clean_up_tokenization_spaces=False), n_in, n_new

    def last_logits(self, texts, hidden_states=False):
        torch = self.torch
        enc = self._enc(texts)
        with torch.no_grad():
            out = self.model.model(**enc, output_hidden_states=hidden_states)  # avoid full-vocab logits
            logits = self.model.lm_head(out.last_hidden_state[:, -1]).float()
        return logits, (out.hidden_states if hidden_states else None)

    def option_probs(self, texts, option_keys_list):
        """Forced-prefix next-token distribution over the item's option letters.
        Returns (probs dict renormalised over options, raw letter mass) per item."""
        logits, _ = self.last_logits(texts)
        lp = self.torch.log_softmax(logits, -1)
        res = []
        for i, keys in enumerate(option_keys_list):
            ids = [self.letter_ids[k] for k in keys]
            l = lp[i, ids]
            mass = float(l.exp().sum())
            p = self.torch.softmax(l, -1).tolist()
            res.append(({k: round(float(x), 6) for k, x in zip(keys, p)}, round(mass, 6)))
        return res


def load_runner(out: Path, key: str, load_in_4bit: bool = False) -> Runner:
    """Load a model for any step. The commit and quantization recorded by the first run of this model
    in `out` are reused, so every condition of a model runs on the same weights (brief 3.1/3.2) even
    if the Hugging Face repo is updated between steps. Start a fresh --out directory to re-pin."""
    revision = None
    mf = Path(out) / "raw" / key / "run_manifest.json"
    if mf.exists():
        j = json.loads(mf.read_text())
        if bool(j.get("quantization")) != bool(load_in_4bit):
            raise SystemExit(f"{key}: earlier runs in {mf.parent} used quantization={j.get('quantization')}. "
                             "The brief requires one setting for all conditions of a model: use the same "
                             "--load-in-4bit setting, or start a fresh --out directory.")
        revision = j.get("model_revision")
        if revision:
            log.info("%s: using the revision pinned by earlier runs: %s", key, revision)
    runner = Runner(key, load_in_4bit, revision=revision)
    INFERENCE["load_in_4bit"] = bool(load_in_4bit)
    INFERENCE["dtype"] = "nf4(compute float16)" if load_in_4bit else "float16"
    return runner


def free_runner(runner):
    """Release GPU memory so the next model can be loaded (brief: one model at a time)."""
    import gc
    import torch
    del runner.model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


# =============================================================================
# RUN THIS STEP
# =============================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", nargs="*", default=[], choices=list(MODELS))
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--data-file", default=None, help="local JSONL copy of the fixed revision (offline)")
    ap.add_argument("--load-in-4bit", action="store_true", help="NF4; only if fp16 does not fit")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)
    out = Path(a.out)

    rows = load_dataset(out, a.data_file)
    man = json.loads((out / "raw" / "dataset_manifest.json").read_text())
    print(f"\nDataset: {len(rows)} rows, resolved revision {man['resolved_revision']}")
    print("Subsets:", {k: len(subset(rows, k)) for k in SUBSETS})
    print(f"Validation issues ({len(man['issues'])}):")
    for i in man["issues"][:20]:
        print("  ", i)
    r0 = rows[0]
    print(f"\nRow 0 fields: {sorted(r0)}")
    print(f"id={r0['id']} gold={r0['answer']} type1_injection_key={r0['type1_injection_key']}")
    print("question:", r0["question"][:400])
    print("options:", json.dumps(r0["options"], indent=1)[:600])

    for key in a.model:
        print(f"\n{'#' * 20} {key} {'#' * 20}")
        runner = load_runner(out, key, a.load_in_4bit)
        print(f"{runner.hf_id} @ {runner.revision}")
        print(runner.versions)
        # A toy prompt only -- the real benchmark prompt is introduced in step 2.
        opts = "\n".join(f"{k}. {v}" for k, v in r0["options"].items())
        msgs = [{"role": "user", "content": r0["question"] + "\n\n" + opts + "\n\nAnswer with one option letter."}]
        text = runner.render(msgs)
        print("\nRendered chat template:\n" + text[-800:])
        gen, n_in, n_new = runner.generate([text])
        print(f"\nModel output ({n_in[0]} input tokens, {n_new[0]} new): {gen[0][:300]!r}  (gold {r0['answer']})")
        free_runner(runner)
    print("\nStep 1 finished.")


__all__ = [n for n in dir() if not n.startswith("__")]  # so the next step can `from ... import *`


if __name__ == "__main__":
    main()