"""Summarise the LLM labeller's C1/C2 labels on every in-scope both-reject episode.

- Checks the labels against every hand label they overlap (same episodes as the eval set, plus the few-shot ones).
- C1 share by family and by condition, and C1 counts per run.

Usage:  uv run --with scikit-learn python pilot/summarise_all.py pilot/outputs_all_qwen3-32b.jsonl
Writes  pilot/all_labels_<tag>.csv, pilot/all_runs_<tag>.csv, pilot/all_metrics_<tag>.json
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from sklearn.metrics import accuracy_score, cohen_kappa_score

sys.path.insert(0, "pilot")
from evaluate import parse  # noqa: E402


def main():
    out_path = Path(sys.argv[1])
    tag = out_path.stem.replace("outputs_all_", "")
    fam = {json.loads(l)["id"]: json.loads(l)["family"] for l in open("pilot/prompts_all.jsonl", encoding="utf-8")}
    hand = {}
    for f in ("combined_dm_episodes.csv", "label_subset_A_small_labelled.csv"):
        for e in csv.DictReader(open(f, encoding="utf-8-sig")):
            if e["alice_verdict_on_bob"] == e["bob_verdict_on_alice"] == "reject":
                hand[(e["run_id"], int(e["evaluation_episode"]))] = "C1" if e["episode_category"].startswith("C1") else "C2"
    cond = {}
    rows = []
    for line in open(out_path, encoding="utf-8"):
        o = json.loads(line)
        _, rid, ep = o["id"].split("|")
        lab, ev = parse(o["raw"])
        rows.append({"run_id": rid, "ep": int(ep), "family": fam[o["id"]], "llm": lab, "evidence": ev,
                     "hand": hand.get((rid, int(ep)), "")})
    rows.sort(key=lambda r: (r["run_id"], r["ep"]))
    with open(f"pilot/all_labels_{tag}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    ok = [r for r in rows if r["llm"]]
    both = [r for r in ok if r["hand"]]
    y, p = [r["hand"] for r in both], [r["llm"] for r in both]
    by_fam = defaultdict(list)
    for r in ok:
        by_fam[r["family"]].append(r)
    runs = defaultdict(lambda: {"n_both_reject": 0, "n_C1": 0})
    for r in ok:
        runs[r["run_id"]]["n_both_reject"] += 1
        runs[r["run_id"]]["n_C1"] += r["llm"] == "C1"
    for rid in runs:
        runs[rid]["condition_id"] = rid.rsplit("__", 1)[0]
        runs[rid]["family"] = rid.split("__")[0]
    with open(f"pilot/all_runs_{tag}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["run_id", "family", "condition_id", "n_both_reject", "n_C1"])
        w.writeheader()
        w.writerows({"run_id": k} | v for k, v in sorted(runs.items()))
    by_cond = defaultdict(lambda: [0, 0])
    for v in runs.values():
        by_cond[v["condition_id"]][0] += v["n_C1"]
        by_cond[v["condition_id"]][1] += v["n_both_reject"]
    m = {"model_tag": tag, "n": len(rows), "runs": len(runs), "parse_failures": len(rows) - len(ok),
         "C1_share": round(sum(r["llm"] == "C1" for r in ok) / len(ok), 3),
         "check_vs_hand": {"n": len(both), "accuracy": round(accuracy_score(y, p), 3), "kappa": round(cohen_kappa_score(y, p), 3),
                           "note": "includes the 6 few-shot episodes, so slightly optimistic"},
         "by_family": {f: {"n": len(v), "C1_share": round(sum(r["llm"] == "C1" for r in v) / len(v), 3),
                           "runs_with_any_C1": round(sum(1 for x in runs.values() if x["family"] == f and x["n_C1"] > 0) /
                                                     max(1, sum(1 for x in runs.values() if x["family"] == f)), 3)}
                       for f, v in sorted(by_fam.items())},
         "by_condition_C1_share": {c: round(a / b, 3) for c, (a, b) in sorted(by_cond.items())},
         "run_C1_count_distribution": dict(sorted(Counter(v["n_C1"] for v in runs.values()).items()))}
    meta = out_path.with_name(out_path.stem + "_meta.json")
    if meta.exists():
        m["run"] = json.load(open(meta))
    json.dump(m, open(f"pilot/all_metrics_{tag}.json", "w"), indent=1)
    print(json.dumps(m, indent=1))


if __name__ == "__main__":
    main()
