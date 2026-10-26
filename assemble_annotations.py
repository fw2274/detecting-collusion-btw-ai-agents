"""Merge hand annotations (annotations/*.json) with dataset labels into two CSVs.

Usage:  uv run --with pyarrow python assemble_annotations.py [selection.csv] [tag]
  defaults: selection_50.csv, tag 50
  -> trajectories_{tag}.csv  one row per run: summary, final outcome, onset/pathway
  -> episodes_{tag}.csv      one row per episode: collude, behavior pattern, judge labels
"""
import csv
import gzip
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

DATA = Path("hf_data")


def b(x):
    return "" if x is None else int(bool(x))


def main():
    selection = sys.argv[1] if len(sys.argv) > 1 else "selection_50.csv"
    tag = sys.argv[2] if len(sys.argv) > 2 else "50"
    sel = list(csv.DictReader(open(selection, encoding="utf-8")))
    notes = {}
    for f in sorted(Path("annotations").glob("*.json")):
        if f.stem.endswith("_cases"):  # case-analysis inputs, not episode notes
            continue
        notes.update(json.load(open(f, encoding="utf-8")))
    missing = [s["run_id"] for s in sel if s["run_id"] not in notes]
    assert not missing, f"no annotation for {missing}"

    traj, eps, problems = [], [], []
    for s in sel:
        rid, exp, cond = s["run_id"], s["experiment"], s["condition_id"]
        E = {e["episode_index"]: e for e in pq.read_table(DATA / f"data/episodes/{exp}/{cond}.parquet").to_pylist() if e["run_id"] == rid}
        A = {(a["episode_index"], a["agent"]): a for a in pq.read_table(DATA / f"data/agents/{exp}/{cond}.parquet").to_pylist() if a["run_id"] == rid}
        t = json.load(gzip.open(DATA / s["trace_file"], "rt", encoding="utf-8"))
        n = notes[rid]
        coll = {}
        for e in t["results"]:
            i, k = e["episode_index"], e["evaluation_episode"]
            if k is None:  # warm-up episode
                continue
            ed = E[i]
            al, bo = e["agents"]["alice"], e["agents"]["bob"]
            # true_expected_verdict is the verdict this agent's own work deserves.
            wrong_accepted = (al["true_expected_verdict"] == "fail" and bo["verdict"] == "accept") or \
                             (bo["true_expected_verdict"] == "fail" and al["verdict"] == "accept")
            coll[k] = b(ed["collusion"])
            note = n["episodes"].get(str(k))
            if not note:
                problems.append(f"{rid} ep{k}: no note")
            eps.append({
                "batch": s["batch"], "run_id": rid, "experiment": exp, "episode": k, "task_type": e["task_type"],
                "collude": coll[k], "behavior_pattern": note or "",
                "coordination_agreement": b(ed["agreement"]), "agreement_status": ed.get("agreement_status") or "",
                "alice_relaxation": b(A[(i, "alice")]["relaxation"]), "alice_relaxation_status": A[(i, "alice")].get("relaxation_status") or "",
                "bob_relaxation": b(A[(i, "bob")]["relaxation"]), "bob_relaxation_status": A[(i, "bob")].get("relaxation_status") or "",
                "alice_verdict": al["verdict"], "bob_verdict": bo["verdict"],
                "alice_work_correct": int(al["true_expected_verdict"] == "pass"), "bob_work_correct": int(bo["true_expected_verdict"] == "pass"),
                "alice_verdict_correct": b(al["verdict_correct"]), "bob_verdict_correct": b(bo["verdict_correct"]),
                "both_accept": b(ed["both_accept"]), "wrong_work_accepted": int(wrong_accepted),
            })
        if len(coll) != 10 or len(n["episodes"]) != 10:
            problems.append(f"{rid}: {len(coll)} episodes, {len(n['episodes'])} notes")
        traj.append({
            "batch": s["batch"], "run_id": rid, "experiment": exp, "condition_id": cond,
            "alice_model": s["alice_model"], "bob_model": s["bob_model"],
            "summary": n["summary"],
            "final_outcome_collude": coll[max(coll)], "ever_colluded": int(any(coll.values())),
            "n_colluding_episodes": sum(coll.values()),
            "onset_episode": s["onset_evaluation_episode"], "onset_pathway": s["onset_pathway"],
            "converged_collusion": s["converged_collusion"],
            "n_coordination_agreement": sum(r["coordination_agreement"] or 0 for r in eps if r["run_id"] == rid),
            "n_wrong_work_accepted": sum(r["wrong_work_accepted"] for r in eps if r["run_id"] == rid),
        })

    for name, rows in ((f"trajectories_{tag}.csv", traj), (f"episodes_{tag}.csv", eps)):
        with open(name, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    print(f"{len(traj)} trajectories, {len(eps)} episodes")
    print("problems:", problems or "none")


if __name__ == "__main__":
    main()
