# Subtask A pilot: LLM labeller on Modal (2026-10-25)

Subtask A is C1 (legitimate coordination) vs C2 (no coordination) on both-reject episodes. The text model alone can't learn it (reject-branch κ 0.01), so we tried an LLM labeller.

## Setup

| | |
|---|---|
| Model | Qwen/Qwen3-32B-FP8, thinking off |
| GPU | 1 × H100 80GB on Modal (`modal/labeller.py`, app `salt-c1c2-labeller`) |
| Serving | vLLM 0.10.2 offline `LLM.chat`, prefix caching, max length 8,192 |
| Decoding | Greedy, at most 200 tokens, guided JSON `{"label": "C1"/"C2", "evidence": "..."}` |
| Prompt | C1/C2 rule plus 6 few-shot examples (3 C1, 3 C2) from the verified small set (`results/labeller/build_prompts.py`); messages cut to 600 characters |
| Inputs | 102 hand-labelled both-reject episodes (eval, few-shot examples excluded) and 652 pilot episodes from 5 runs × 36 conditions |

## Run

| | |
|---|---|
| Prompts | 754 (2.90M prompt tokens, 33k output tokens) |
| Time | 246 s load + 860 s generation = 1,122 s wall (18.7 min) |
| Cost | about $1.25 at about $4/h for an H100 |
| Parse failures | 0 |
| Full dataset | 6,459 both-reject episodes is about 8.6× this run: about 2 h of generation, about $8 |

## Results (`results/labeller/metrics_qwen3-32b.json`)

**LLM vs hand labels**, 102 episodes from 48 runs, all families pooled:

| Metric | Value |
|---|---|
| Accuracy | 0.735 |
| Cohen's κ | 0.47 (95% CI 0.20–0.69, run bootstrap) |
| C1 count, hand vs LLM | 49 vs 48 |
| Confusion | 14 hand-C1 called C2, 13 hand-C2 called C1 |

**κ by family:**

| Family | κ | n |
|---|---|---|
| memory length | 0.63 | 27 |
| cross-model | 0.60 | 8 |
| feedback | 0.40 | 21 |
| main | 0.35 | 35 |

The other families have 4 or fewer episodes each, too few to read.

**κ by annotator:**

| Annotator | κ |
|---|---|
| Claude | 0.58 |
| Chengxiao | 0.43 |
| DM | 0.21 |

**Pilot C1 share by family:**

| Family | C1 share |
|---|---|
| feedback | 0.62 |
| memory scope | 0.61 |
| reward scope | 0.56 |
| memory length | 0.51 |
| warm-up | 0.44 |
| reward type | 0.35 |
| main | 0.27 |
| cross-model | 0.25 |

**Distillation.** TF-IDF + logistic regression trained on the 652 LLM pilot labels scores κ 0.37 on the hand labels. The same model trained on hand labels (5-fold, grouped by run) scores κ 0.19. LLM labels are a better training signal than our ~100 hand labels.

**In `results/labeller/train_labeler.py`** (whole-run held-out, 342 hand episodes; `results/labeller/train_c5a.log`):

| Variant | Reject-branch κ (n=108) | Accuracy | Accept-branch κ (C3/C5a/C5) |
|---|---|---|---|
| Hand labels only | 0.01 | 0.84 | 0.99 |
| + LLM label as a feature | 0.29 | 0.88 | 0.99 |
| LLM label directly (`llm_only`) | 0.44 | 0.90 | 0.99 |
| + LLM pilot labels as training data (`--llm-as-train`) | 0.44 | 0.90 | 0.99 |

## Reading

- κ 0.47 is moderate. It beats every text model, but it's not good enough to replace hand labels for family-level C1 conclusions without a check. The CI is wide because there are only 48 runs.
- Agreement is lowest with DM's batch (κ 0.21). That points to a rule difference in how C1 was read, not just model error. Worth a look at `results/labeller/labels_qwen3-32b.csv` against DM's C1 calls before scaling up.
- **Next, if scaling up:** run the LLM over all 6,459 both-reject episodes (about 2 h, about $8), or first try a larger model or full-length messages on the 102 eval episodes (a few minutes each) to see whether κ moves.
