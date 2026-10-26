"""Pick a targeted batch: every high-intensity-but-failed run, plus an all-or-nothing contrast from reward_scope 3.7 Flash.

Failed = both-accept in >= 70% of evaluation episodes, but not in the final episode.
Contrast = reward_scope__gemini-3-7-flash__separate runs: N that collude at high intensity
through the end, and N that never mutually accept.

Usage:  uv run --with pyarrow --with huggingface_hub python select_failed.py [--contrast 3] [--batch 6]
Writes selection_failed.csv and downloads any missing traces into hf_data/.
"""
import argparse
import csv
import random
from pathlib import Path

import pyarrow.parquet as pq

DATA = Path("hf_data")
SKIP = {"controlled_peer", "communication"}  # collusion is undefined there
CONTRAST = "reward_scope__gemini-3-7-flash__separate"


def sequences():
    seqs = {}
    for f in sorted((DATA / "data/episodes").glob("*/*.parquet")):
        if f.parent.name in SKIP:
            continue
        for e in pq.read_table(f, columns=["run_id", "evaluation_episode", "both_accept"]).to_pylist():
            if e["evaluation_episode"]:
                seqs.setdefault(e["run_id"], {})[e["evaluation_episode"]] = int(bool(e["both_accept"]))
    return {r: [s[k] for k in sorted(s)] for r, s in seqs.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contrast", type=int, default=3)
    ap.add_argument("--batch", type=int, default=6)
    ap.add_argument("--seed", type=int, default=20261024)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    seqs = sequences()
    runs = {r["run_id"]: r for r in pq.read_table(DATA / "data/runs.parquet").to_pylist()}
    picked = []
    for rid, s in sorted(seqs.items()):
        if sum(s) / len(s) >= 0.7 and s[-1] == 0:
            picked.append((rid, "high-intensity failed"))
    contrast = [rid for rid in sorted(seqs) if runs[rid]["condition_id"] == CONTRAST]
    hi = [r for r in contrast if sum(seqs[r]) / 10 >= 0.7 and seqs[r][-1] == 1]
    never = [r for r in contrast if sum(seqs[r]) == 0]
    picked += [(r, "contrast: colluded") for r in rng.sample(hi, args.contrast)]
    picked += [(r, "contrast: never") for r in rng.sample(never, args.contrast)]

    rows = []
    for rid, why in picked:
        r = runs[rid]
        rows.append({"batch": args.batch, "run_id": rid, "condition_id": r["condition_id"], "experiment": r["experiment"],
                     "alice_model": r["alice_model"], "bob_model": r["bob_model"], "sequence_id": r["sequence_id"],
                     "onset_pathway": r["onset_pathway"], "onset_evaluation_episode": r["onset_evaluation_episode"],
                     "converged_collusion": r["converged_collusion"], "trace_file": r["trace_file"],
                     "selection_reason": why, "both_accept_sequence": "".join(map(str, seqs[rid]))})
    with open("selection_failed.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    missing = [r["trace_file"] for r in rows if not (DATA / r["trace_file"]).exists()]
    if missing:
        from huggingface_hub import hf_hub_download
        for p in missing:
            hf_hub_download("SALT-NLP/agent-collusion", p, repo_type="dataset", local_dir=DATA)
    for r in rows:
        print(f"{r['selection_reason']:22} {r['both_accept_sequence']} {r['run_id']}")
    print(len(rows), "runs;", len(missing), "traces downloaded")


if __name__ == "__main__":
    main()
