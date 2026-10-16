### llama — useful: largest occlusion top−random gap — row 18 (MEDMISQA_1195)
gold=A, pred=F (p=0.92), sentences=11, k=2

- top occlusion sentence (Δlogp 4.777): "She has a history of a seizure disorder controlled by lamotrigine; other medications include folic acid, iron supplements, and a multivitamin."
- deletion: {"occlusion": {"top": 4.79158, "bottom": -0.05043, "random_mean_drop": 0.30634}, "gradxinput": {"top": -0.03545, "bottom": 4.50597, "random_mean_drop": 0.30634}}
- evidence: The patient has a history of seizure disorder controlled by lamotrigine, which is a known teratogen that can cause fetal hydantoin syndrome, characterized by a range of congenital anomalies including heart defects, cleft palate, and developmental delays.
- evidence-cited sentence idx: 5

### llama — misleading: grad×input top-k hurts less than random — row 38 (MEDMISQA_1954)
gold=B, pred=C (p=0.30), sentences=15, k=3

- top occlusion sentence (Δlogp 1.007): "A 25-year-old man is brought to the emergency department by his wife for evaluation of abnormal behavior that began 2 weeks ago."
- deletion: {"occlusion": {"top": 1.46006, "bottom": -0.88559, "random_mean_drop": 0.5698920000000001}, "gradxinput": {"top": -0.54291, "bottom": -0.19647, "random_mean_drop": 0.56916}}
- evidence: The patient's symptoms of excessive drinking, agitation, pressured speech, and tangential thought process are consistent with a diagnosis of bipolar disorder, specifically a manic episode. Lithium is a commonly used long-term treatment for bipolar disorder to prevent future episodes and reduce symptoms.
- evidence-cited sentence idx: 10

### llama — rationale vs attribution mismatch — row 0 (MEDMISQA_103)
gold=E, pred=E (p=0.86), sentences=11, k=2

- top occlusion sentence (Δlogp 0.196): "The patient requests pain medication."
- deletion: {"occlusion": {"top": 0.60176, "bottom": -0.1005, "random_mean_drop": 0.23031599999999997}, "gradxinput": {"top": 0.08811, "bottom": 0.0137, "random_mean_drop": 0.228034}}
- evidence: The patient's history of opioid use disorder and current methadone maintenance treatment, combined with his request for pain medication, raises concerns for potential opioid-seeking behavior. Scheduled short-acting opioid administration, such as acetaminophen or ibuprofen, is a safer alternative to provide pain relief while minimizing the risk of opioid diversion or misuse.
- evidence-cited sentence idx: 2

### qwen — useful: largest occlusion top−random gap — row 37 (MEDMISQA_1894)
gold=E, pred=A (p=1.00), sentences=13, k=3

- top occlusion sentence (Δlogp 7.500): "Contrast esophagram with gastrografin shows mild leakage of contrast from the lower esophagus into the mediastinum without contrast extravasation into the pleural and peritoneal cavities."
- deletion: {"occlusion": {"top": 27.63102, "bottom": 0.0, "random_mean_drop": 0.8775040000000001}, "gradxinput": {"top": 0.00223, "bottom": 0.63263, "random_mean_drop": 0.8775040000000001}}
- evidence: The patient has mild leakage of contrast from the lower esophagus into the mediastinum, which is a common finding in bulimia nervosa due to chronic vomiting. Intravenous octreotide therapy is effective in reducing salivary gland hyperplasia and esophageal leak, making it the most appropriate next step in managing this patient's condition.
- evidence-cited sentence idx: 11

### qwen — misleading: grad×input top-k hurts less than random — row 15 (MEDMISQA_828)
gold=A, pred=B (p=1.00), sentences=11, k=2

- top occlusion sentence (Δlogp 8.188): "Pelvic ultrasonography shows a pregnancy at an estimated 15 weeks' gestation."
- deletion: {"occlusion": {"top": 13.81551, "bottom": -0.0, "random_mean_drop": 6.69853}, "gradxinput": {"top": -0.0, "bottom": -0.0, "random_mean_drop": 6.69853}}
- evidence: The patient's symptoms of accelerated speech, switching the conversation to the natural habitat of bees, and daytime sleepiness are indicative of a psychotic episode, which is consistent with a diagnosis of schizophrenia. Given her history of aripiprazole not being effective and the recent switch to risperidone, which is an antipsychotic, the most appropriate next step is to schedule an abortion as she is pregnant and the voices are telling her to undergo a cleanse, which is not a medical or ethical recommendation.
- evidence-cited sentence idx: 6

### qwen — rationale vs attribution mismatch — row 3 (MEDMISQA_216)
gold=D, pred=B (p=0.67), sentences=10, k=2

- top occlusion sentence (Δlogp 3.291): "To reduce the likelihood of the patient developing her current symptoms, a drug with which of the following mechanisms of action should have been prescribed instead of her current medication?"
- deletion: {"occlusion": {"top": 4.23961, "bottom": -0.39268, "random_mean_drop": 0.03062}, "gradxinput": {"top": 4.23961, "bottom": 0.74456, "random_mean_drop": 0.03062}}
- evidence: The patient's symptoms of restlessness, anxiety, and chest tightness are consistent with a psychotic illness. Haloperidol, an antipsychotic, is being used. NMDA receptor antagonists, such as ketamine, are known to induce symptoms similar to those described, including agitation and psychosis. Therefore, an NMDA receptor antagonist should have been avoided in this case.
- evidence-cited sentence idx: 2
