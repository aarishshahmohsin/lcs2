import torch
from step2_baseline import *

rows = load_dataset(Path(DEFAULT_OUT))
r = Runner("llama")
batch = subset(rows, "core")[32:40]          # original batch of 8; row 38 is position 6
i = 6
cid, eid = r.letter_ids["C"], r.letter_ids["E"]
texts = [r.render(build_messages(x, "clean")) for x in batch]

# 1) generation pass: raw logits at every step
enc = r._enc(texts)
with torch.no_grad():
    out = r.model.generate(**enc, generation_config=r.gen_config,
                           output_logits=True, return_dict_in_generate=True)
gen = out.sequences[i, enc["input_ids"].shape[1]:].tolist()
print([(j, t, repr(r.tok.decode([t]))) for j, t in enumerate(gen[:8])])
step = next(j for j, t in enumerate(gen) if t in (cid, eid))
lg = out.logits[step][i]
print("generation step", step, " C", lg[cid].item(), " E", lg[eid].item())

# 2) scoring pass, same batch (what was saved)
lb, _ = r.last_logits([t + ANSWER_PREFIX for t in texts])
print("scoring, batch of 8:  C", lb[i, cid].item(), " E", lb[i, eid].item())

# 3) scoring pass, alone (your diagnostic)
l1, _ = r.last_logits([texts[i] + ANSWER_PREFIX])
print("scoring, alone:      C", l1[0, cid].item(), " E", l1[0, eid].item())
print("fp16 step at 28:", 2**-6)