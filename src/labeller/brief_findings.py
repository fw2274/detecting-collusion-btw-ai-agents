"""Recompute the team brief's headline findings on the 1,800 in-scope runs, from the dataset fields alone.

Usage:  uv run --with pyarrow --with pandas python src/labeller/brief_findings.py
Writes  results/labeller/brief_findings.json
"""
import glob
import json
import os

import pandas as pd

COLS = ["run_id", "condition_id", "evaluation_episode", "alice_verdict", "bob_verdict", "alice_task_correct",
        "bob_task_correct", "both_accept", "agreement", "alice_cross_episode_memory_length", "alice_model"]
parts = []
for f in sorted(glob.glob("hf_data/data/episodes/*/*.parquet")):
    fam = os.path.basename(os.path.dirname(f))
    if fam in ("controlled_peer", "communication"):
        continue
    d = pd.read_parquet(f, columns=COLS)
    parts.append(d[d.evaluation_episode.notna()].assign(family=fam))
e = pd.concat(parts, ignore_index=True).sort_values(["run_id", "evaluation_episode"])
e["ba"] = e.both_accept.astype(bool)
e["agr"] = e.agreement.astype(float).eq(1)
runs = pd.read_parquet("hf_data/data/runs.parquet")
e = e.merge(runs[["run_id", "onset_pathway"]], on="run_id")
out = {"runs": int(e.run_id.nunique()), "episodes": len(e)}

col = e[e.ba]
out["colluding_episodes"] = len(col)
out["judge_flags_share"] = round(col.agr.mean(), 3)
out["judge_flags_by_onset_pathway"] = col.groupby(col.onset_pathway.fillna("No onset")).agr.mean().round(3).to_dict()
# run level: colluding runs the judge flags at least once
rc = e.groupby("run_id").agg(any_col=("ba", "max"), any_judge=("agr", lambda s: bool((s & e.loc[s.index, "ba"]).any())))
out["colluding_runs"] = int(rc.any_col.sum())
out["judge_flags_runs_share"] = round(rc[rc.any_col].any_judge.mean(), 3)

# memory: memory_length family, 0 vs 3 episodes, per model
ml = e[e.family == "memory_length"]
out["memory_length_collusion"] = ml.groupby(["alice_model", "alice_cross_episode_memory_length"]).ba.mean().round(3).unstack().to_dict(orient="index")

# reciprocity and punishment, per agent, previous episode -> this episode
rows = []
for rid, g in e.groupby("run_id"):
    g = g.sort_values("evaluation_episode")
    for me, other in (("alice_verdict", "bob_verdict"), ("bob_verdict", "alice_verdict")):
        mine, theirs = list(g[me]), list(g[other])
        for t in range(1, len(mine)):
            rows.append((mine[t - 1], theirs[t - 1], mine[t]))
tr = pd.DataFrame(rows, columns=["me_prev", "them_prev", "me_now"])
acc = lambda m, t: tr[(tr.me_prev == m) & (tr.them_prev == t)].me_now.eq("accept").mean()
out["switch_to_accept_after_partner_accepted_me_rejected"] = round(acc("reject", "accept"), 3)
out["switch_to_accept_after_mutual_reject"] = round(acc("reject", "reject"), 3)
out["switch_to_reject_after_partner_rejected_me_accepted"] = round(1 - acc("accept", "reject"), 3)
out["switch_to_reject_after_mutual_accept"] = round(1 - acc("accept", "accept"), 3)

# stability: collude again next episode, given collusion now
e["ba_next"] = e.groupby("run_id").ba.shift(-1)
s = e[e.ba & e.ba_next.notna()]
out["collude_again_next_episode"] = round(s.ba_next.astype(bool).mean(), 3)
out["collusion_share_by_episode"] = e.groupby("evaluation_episode").ba.mean().round(3).to_dict()

# harm: colluding episodes where at least one accepted task was wrong
wrong = (~col.alice_task_correct.astype(bool)) | (~col.bob_task_correct.astype(bool))
out["colluding_episodes_with_wrong_work"] = round(wrong.mean(), 3)
json.dump(out, open("results/labeller/brief_findings.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
