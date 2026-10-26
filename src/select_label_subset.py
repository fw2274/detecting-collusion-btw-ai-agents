"""Pick the next hand-labelling subset, sized so subtask A (C1 vs C2) can be validated and subtask B's
acknowledgement clause can be checked. Only runs that have no labels yet are used.

Parts:
  whole_run     7 whole runs in families with few or no labels (warm-up 3, reward scope 2, memory scope 2)
  subtaskA      60 both-reject episodes, one per run, spread over families, half with a log-swap/plan cue
  subtaskB_ack  15 episodes where both accept, one agent announces, and the other replies with an acknowledgement word

Usage:  uv run --with pyarrow python src/select_label_subset.py   -> label_subset.csv (blank hand columns to fill)
"""
import csv
import glob
import json
import os
import random
import re
from collections import defaultdict

import pyarrow.parquet as pq

from build_dm_format import ANNOUNCE_RE, EP_COLS, NOT_ACCEPT_RE

SEED = 20261025
PLAN_RE = re.compile(r"do the same|in parts|in \d parts|in chunks|send mine|let'?s (?:exchange|share|send)|"
                     r"must (?:both )?reject|policy requires|we (?:will|should) both reject|agree", re.I)
ACK_RE = re.compile(r"thanks? for (?:accepting|the accept)|agreed|confirmed|sounds good|likewise|same here|"
                    r"accepting yours|mutual", re.I)
WHOLE = [("warmup", 3), ("reward_scope", 2), ("memory_scope", 2)]
A_PER_FAMILY = {"main": 12, "cross_model": 9, "feedback": 7, "memory_length": 7, "memory_scope": 7,
                "warmup": 8, "reward_scope": 6, "reward_type": 4}


def used_runs():
    used = {r["run_id"] for r in csv.DictReader(open("results/annotation/combined_dm_runs.csv", encoding="utf-8-sig"))}
    used |= {r["run_id"] for r in csv.DictReader(open("results/selection/selection_failed.csv", encoding="utf-8"))}
    used |= {k.split("|")[0] for k in json.load(open("annotations/subtaskB_labels.json", encoding="utf-8")) if "|" in k}
    return used


def main():
    rng = random.Random(SEED)
    used = used_runs()
    eps = defaultdict(list)  # family -> episodes
    for f in sorted(glob.glob("hf_data/data/episodes/*/*.parquet")):
        fam = os.path.basename(os.path.dirname(f))
        if fam in ("controlled_peer", "communication"):
            continue
        for e in pq.read_table(f).to_pylist():
            if e["evaluation_episode"] and e["run_id"] not in used:
                e["family"] = fam
                eps[fam].append(e)

    picked, taken = [], set()

    def add(e, purpose, cue=""):
        picked.append((e, purpose, cue))
        taken.add(e["run_id"])

    # 1. whole runs: one per condition where possible, preferring runs that mix collusion and non-collusion
    for fam, n in WHOLE:
        by_run = defaultdict(list)
        for e in eps[fam]:
            by_run[e["run_id"]].append(e)
        conds = defaultdict(list)
        for rid, es in by_run.items():
            k = sum(x["alice_verdict"] == x["bob_verdict"] == "accept" for x in es)
            conds[rid.rsplit("__", 1)[0]].append((0 < k < 10, rid))
        order = sorted(conds)
        rng.shuffle(order)
        for cond in order[:n]:
            mixed = [rid for m, rid in sorted(conds[cond]) if m] or [rid for _, rid in sorted(conds[cond])]
            rid = rng.choice(mixed)
            for e in sorted(by_run[rid], key=lambda x: x["evaluation_episode"]):
                add(e, "whole_run")

    # 2. subtask A: both-reject episodes, one per run, half with a plan cue
    for fam, n in A_PER_FAMILY.items():
        pool = [e for e in eps[fam] if e["alice_verdict"] == e["bob_verdict"] == "reject" and e["run_id"] not in taken]
        rng.shuffle(pool)
        for want_cue in (True, False):
            k, seen = 0, set()
            for e in pool:
                text = " ".join(m["content"] for m in e["communication"] or [])
                if bool(PLAN_RE.search(text)) != want_cue or e["run_id"] in taken or e["run_id"] in seen:
                    continue
                add(e, "subtaskA", "plan_cue" if want_cue else "no_cue")
                seen.add(e["run_id"])
                k += 1
                if k == (n + 1) // 2 if want_cue else k == n // 2:
                    break

    # 3. subtask B acknowledgement check: one announcer, other side replies with an acknowledgement word
    pool = []
    for fam in eps:
        for e in eps[fam]:
            if not (e["alice_verdict"] == e["bob_verdict"] == "accept") or e["agreement"] or e["run_id"] in taken:
                continue
            msgs = e["communication"] or []
            who = {m["sender"] for m in msgs if ANNOUNCE_RE.search(m["content"]) and not NOT_ACCEPT_RE.search(m["content"])}
            if len(who) == 1:
                other = {"alice", "bob"} - who
                if any(m["sender"] in other and ACK_RE.search(m["content"]) for m in msgs):
                    pool.append(e)
    rng.shuffle(pool)
    seen = set()
    for e in pool:
        if e["run_id"] not in seen and len(seen) < 15:
            add(e, "subtaskB_ack", "ack_word")
            seen.add(e["run_id"])

    rows = []
    for e, purpose, cue in picked:
        rows.append({"selection_purpose": purpose, "selection_cue": cue, "family": e["family"],
                     "batch": "L", "annotator": "", "run_id": e["run_id"], "evaluation_episode": e["evaluation_episode"],
                     "task_type": e["task_type"], "alice_task_correct": int(bool(e["alice_task_correct"])),
                     "bob_task_correct": int(bool(e["bob_task_correct"])), "alice_verdict_on_bob": e["alice_verdict"],
                     "bob_verdict_on_alice": e["bob_verdict"], "coordination_label": int(bool(e["agreement"])),
                     "execution_label": int(bool(e["collusion"])),
                     "both_accept": int(e["alice_verdict"] == e["bob_verdict"] == "accept")})
    cols = ["selection_purpose", "selection_cue", "family"] + EP_COLS
    with open("results/selection/label_subset.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print(len(rows), "episodes from", len({r["run_id"] for r in rows}), "runs")
    print(Counter(r["selection_purpose"] for r in rows))
    print(Counter((r["selection_purpose"], r["family"]) for r in rows))


if __name__ == "__main__":
    main()


def shrink_subtask_a(per_family=3, cue_share=2):
    """Smaller subtask-A set when there is no time for the full subset: from label_subset.csv's subtask-A rows,
    take `per_family` episodes per family (`cue_share` with a plan cue, the rest without), keeping file order.
    Writes label_subset_A_small.csv."""
    rows = [r for r in csv.DictReader(open("results/selection/label_subset.csv", encoding="utf-8-sig")) if r["selection_purpose"] == "subtaskA"]
    out, cols = [], None
    for fam in sorted({r["family"] for r in rows}):
        fr = [r for r in rows if r["family"] == fam]
        cue = [r for r in fr if r["selection_cue"] == "plan_cue"][:cue_share]
        rest = [r for r in fr if r["selection_cue"] == "no_cue"][:per_family - len(cue)]
        out += cue + rest
    with open("results/selection/label_subset_A_small.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(out)
    print(len(out), "subtask-A episodes in label_subset_A_small.csv")
