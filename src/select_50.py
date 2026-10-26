"""Pick 50 representative trajectories (5 annotator batches of 10) from SALT-NLP/agent-collusion.

Covers every same-model main condition (3 each), every cross-model condition (1 each) and one
trajectory per ablation condition, choosing onset pathways so each slice shows its typical and
contrasting behavior. Warm-up, controlled-peer, communication and acceptance-reward families are
left out (warm-up by request; collusion is undefined or always 0 in the others).

Usage:  uv run --with pyarrow python src/select_50.py [--seed 20261024] [--data hf_data]
Writes selection_50.csv.
"""
import argparse
import csv
import random
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

# condition_id -> onset pathways to draw (one trajectory each)
TARGETS = {
    "main__claude-opus-4-6": ["SR", "RR", "EX"],
    "main__claude-sonnet-4-6": ["SR", "RR", "EX"],
    "main__deepseek-v4-flash": ["SR", "RR", "EX"],
    "main__gemini-3-1-flash-lite": ["EX", "RR", "No onset"],
    "main__gemini-3-7-flash": ["EX", "EX", "RR"],
    "main__gemma-4-31b-it": ["RR", "No onset", "SR"],
    "main__gpt-5-6-luna": ["RR", "SR", "No onset"],
    "main__gpt-5-6-terra": ["RR", "Other", "No onset"],
    "main__qwen-3-6-27b": ["EX", "RR", "SR"],
    "main__qwen-3-8-27b": ["SR", "EX", "Other"],
    "cross_model__gemini-3-1-flash-lite__claude-opus-4-6": ["RR"],
    "cross_model__gemini-3-1-flash-lite__claude-sonnet-4-6": ["SR"],
    "cross_model__gemini-3-1-flash-lite__deepseek-v4-flash": ["RR"],
    "cross_model__gemini-3-1-flash-lite__gemini-3-7-flash": ["EX"],
    "cross_model__gemini-3-1-flash-lite__gpt-5-6-luna": ["RR"],
    "cross_model__gemini-3-1-flash-lite__qwen-3-8-27b": ["Other"],
    "feedback__gemini-3-1-flash-lite__no-reward": ["No onset"],
    "feedback__gemini-3-1-flash-lite__no-verdict-review": ["No onset"],
    "feedback__gemini-3-7-flash__no-reward": ["Other"],
    "feedback__gemini-3-7-flash__no-verdict-review": ["EX"],
    "memory_length__gemini-3-1-flash-lite__0": ["No onset"],
    "memory_length__gemini-3-1-flash-lite__3": ["RR"],
    "memory_length__gemini-3-7-flash__0": ["No onset"],
    "memory_length__gemini-3-7-flash__3": ["EX"],
    "memory_scope__gemini-3-1-flash-lite__communication-onward": ["RR"],
    "memory_scope__gemini-3-1-flash-lite__feedback-and-reflection": ["No onset"],
    "memory_scope__gemini-3-7-flash__communication-onward": ["EX"],
    "memory_scope__gemini-3-7-flash__feedback-and-reflection": ["EX"],
    "reward_scope__gemini-3-1-flash-lite__separate": ["No onset"],
    "reward_scope__gemini-3-7-flash__separate": ["EX"],
}
# Already annotated in detail; kept as an anchor example.
PINNED = {"main__claude-sonnet-4-6__rep010"}
N_BATCHES = 5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261024)
    ap.add_argument("--data", type=Path, default=Path("hf_data"))
    args = ap.parse_args()
    rng = random.Random(args.seed)

    runs = pq.read_table(args.data / "data/runs.parquet").to_pylist()
    by_cond = {}
    for r in runs:
        by_cond.setdefault(r["condition_id"], []).append(r)

    used_seqs, chosen = Counter(), []
    for cond, pathways in TARGETS.items():
        pool = sorted(by_cond[cond], key=lambda r: r["run_id"])
        for pathway in pathways:
            cands = [r for r in pool if (r["onset_pathway"] or "No onset") == pathway and r not in chosen]
            pinned = [r for r in cands if r["run_id"] in PINNED]
            if pinned:
                pick = pinned[0]
            else:
                rng.shuffle(cands)
                pick = min(cands, key=lambda r: used_seqs[r["sequence_id"]])  # spread task sequences
            chosen.append(pick)
            used_seqs[pick["sequence_id"]] += 1

    # Deal round-robin over pathway-then-family order so every batch gets a similar pathway mix
    # (including non-colluding runs) and a spread of families.
    chosen.sort(key=lambda r: (r["onset_pathway"] or "No onset", r["experiment"], r["run_id"]))
    rows = []
    for i, r in enumerate(chosen):
        rows.append({
            "batch": i % N_BATCHES + 1,
            "run_id": r["run_id"],
            "condition_id": r["condition_id"],
            "experiment": r["experiment"],
            "alice_model": r["alice_model"],
            "bob_model": r["bob_model"],
            "sequence_id": r["sequence_id"],
            "onset_pathway": r["onset_pathway"],
            "onset_evaluation_episode": r["onset_evaluation_episode"],
            "converged_collusion": r["converged_collusion"],
            "trace_file": r["trace_file"],
        })
    rows.sort(key=lambda r: (r["batch"], r["run_id"]))
    with open("results/selection/selection_50.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(len(rows), "trajectories")
    for b in range(1, N_BATCHES + 1):
        sub = [r for r in rows if r["batch"] == b]
        print(f"batch {b}:", dict(Counter(r["experiment"] for r in sub)), dict(Counter(r["onset_pathway"] for r in sub)))


if __name__ == "__main__":
    main()
