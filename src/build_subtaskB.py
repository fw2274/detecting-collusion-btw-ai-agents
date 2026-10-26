"""Turn hand-label files for single episodes into rows in the combined episode schema.

Usage:  uv run --with pyarrow python src/build_subtaskB.py
  annotations/subtaskB_labels.json -> subtaskB_examples.csv            (batch "B", C3 vs C5 balancing set)
  annotations/subtaskA_labels.json -> label_subset_A_small_labelled.csv (batch "A", C1 vs C2 small set)
Trace and dataset columns come from the parquet.
"""
import csv
import json
from pathlib import Path

import pyarrow.parquet as pq

from build_dm_format import CAT_NAME, EP_COLS, implied_category, write

DATA = Path("hf_data")


def build(labels_path, out_path, batch):
    data = json.load(open(labels_path, encoding="utf-8"))
    labels = {k: v for k, v in data.items() if "|" in k}
    verified = data.get("_verified")  # set once a reviewer has checked every label in the file
    source = f'Claude, verified by {verified["by"]} {verified["date"]}' if verified else "Claude"
    rows = []
    for key, lab in labels.items():
        rid, k = key.split("|")
        k = int(k)
        cond = rid.rsplit("__", 1)[0]
        exp = cond.split("__")[0]
        e = next(x for x in pq.read_table(DATA / f"data/episodes/{exp}/{cond}.parquet").to_pylist()
                 if x["run_id"] == rid and x["evaluation_episode"] == k)
        rel = {a["agent"]: a["relaxation"] for a in pq.read_table(DATA / f"data/agents/{exp}/{cond}.parquet",
               columns=["run_id", "episode_index", "agent", "relaxation"]).to_pylist()
               if a["run_id"] == rid and a["episode_index"] == e["episode_index"]}
        msg = next(m for m in e["communication"] if m["sender"] == lab["quote"][0] and m["round"] + 1 == lab["quote"][1])
        assert lab["quote"][2][:40] in msg["content"], key
        a_ok, b_ok = bool(e["alice_task_correct"]), bool(e["bob_task_correct"])
        both, agree = e["alice_verdict"] == e["bob_verdict"] == "accept", bool(e["agreement"])
        rows.append({
            "batch": batch, "annotator": "Claude", "run_id": rid, "evaluation_episode": k, "task_type": e["task_type"],
            "alice_task_correct": int(a_ok), "bob_task_correct": int(b_ok),
            "alice_verdict_on_bob": e["alice_verdict"], "bob_verdict_on_alice": e["bob_verdict"],
            "wrong_work_accepted": int((not b_ok and e["alice_verdict"] == "accept") or (not a_ok and e["bob_verdict"] == "accept")),
            "episode_category": CAT_NAME[{"C2": "C2a"}.get(lab["cat"], lab["cat"])], "collude_hand": int(lab["cat"] in ("C3", "C5")),
            "behavior_pattern": lab.get("pattern") or lab["reason"],
            "evidence_quote": f'{lab["quote"][0].capitalize()}, Ep{k} R{lab["quote"][1]}: "{msg["content"].strip()}"',
            "label_source": source, "claude_filled_fields": "cat;collude;pattern;evidence" + (";borderline" if lab["borderline"] else ""),
            "dataset_category_implied": implied_category(both, agree, e["alice_verdict"], e["bob_verdict"]),
            "coordination_label": int(agree), "execution_label": int(bool(e["collusion"])), "both_accept": int(both),
            "alice_relaxation": "" if rel.get("alice") is None else int(rel["alice"]),
            "bob_relaxation": "" if rel.get("bob") is None else int(rel["bob"]),
            # explicit two-sided C3 rule: C3 = level 2; a C5 marked borderline had an agreed evidence substitute (level 1)
            "talk_level": 2 if lab["cat"] == "C3" else 1 if lab["cat"] == "C5" and lab["borderline"] else 0,
            "borderline": lab["borderline"],
            "episode_category_original": "", "relabel_note": "",
        })
    write(out_path, rows, EP_COLS + ["borderline"])
    print(out_path, len(rows), "rows:", {c: sum(r["episode_category"].startswith(c) for r in rows) for c in ("C1", "C2", "C3", "C5")})


def main():
    build("annotations/subtaskB_labels.json", "results/annotation/subtaskB_examples.csv", "B")
    build("annotations/subtaskA_labels.json", "results/annotation/label_subset_A_small_labelled.csv", "A")


if __name__ == "__main__":
    main()
