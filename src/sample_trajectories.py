"""Draw a stratified annotation sample from SALT-NLP/agent-collusion.

Outputs:
  annotation_sample.csv     one row per sampled trajectory
  annotation_episodes.csv   one row per (trajectory, key episode, agent): blank coordination/execution columns,
                            a pre-filled outcome suggestion, and auto_* fields from the episodes/agents configs

Usage:  uv run --with pyarrow python src/sample_trajectories.py [--seed 20261024] [--cache .hf_cache]
"""
import argparse
import csv
import random
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

HF = "https://huggingface.co/datasets/SALT-NLP/agent-collusion/resolve/main/"
RUNS = "data/runs.parquet"
# Task sequences are shared across conditions, so one agents file gives the task per (sequence, episode, agent).
TASK_SOURCE = "data/agents/main/main__claude-opus-4-6.parquet"

# experiment family -> (trajectories per condition, stratification key)
PLAN = {
    "main": (4, "pathway"),
    "cross_model": (3, "pathway"),
    "feedback": (3, "converged"),
    "memory_length": (3, "converged"),
    "memory_scope": (3, "converged"),
    "reward_scope": (3, "converged"),
    "reward_type": (3, "converged"),
    "controlled_peer": (1, None),
    "communication": (3, None),
}
# warmup family is excluded by design.
DEV_SEQUENCES = range(1, 36)  # 1-35 dev, 36-50 test
N_EPISODES = 10


def fetch(path, cache):
    local = cache / path
    if not local.exists():
        local.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(HF + path, local)
    return pq.read_table(local).to_pylist()


def stratum(run, key):
    if key == "pathway":
        return run["onset_pathway"] or "No onset"
    if key == "converged":
        return str(run["converged_collusion"])
    return "all"


def pick(runs, k, key, rng, used_seqs):
    """Round-robin over strata (most common first) so each condition covers as many strata as possible,
    preferring sequence_ids not yet used anywhere in the sample."""
    groups = defaultdict(list)
    for r in runs:
        groups[stratum(r, key)].append(r)
    for g in groups.values():
        rng.shuffle(g)
        g.sort(key=lambda r: used_seqs[r["sequence_id"]])  # stable: least-used sequences first
    order = sorted(groups, key=lambda s: (-len(groups[s]), s))
    chosen = []
    while len(chosen) < k and any(groups.values()):
        for s in order:
            if groups[s] and len(chosen) < k:
                r = groups[s].pop(0)
                chosen.append(r)
                used_seqs[r["sequence_id"]] += 1
    return chosen


EPISODE_COLS = ["run_id", "episode_index", "alice_verdict", "bob_verdict", "alice_task_correct", "bob_task_correct",
                "alice_verdict_correct", "bob_verdict_correct", "both_accept", "collusion",
                "agreement", "agreement_status"]
AGENT_COLS = ["run_id", "episode_index", "agent", "verdict_forced", "reward", "relaxation", "relaxation_status"]


def load_outcomes(conditions, cache):
    """Index episode- and agent-level outcome fields for the sampled conditions by (run_id, episode_index[, agent])."""
    episodes, agents = {}, {}
    for exp, cond in sorted(conditions):
        for kind, cols, index, store in (
            ("episodes", EPISODE_COLS, lambda r: (r["run_id"], r["episode_index"]), episodes),
            ("agents", AGENT_COLS, lambda r: (r["run_id"], r["episode_index"], r["agent"]), agents),
        ):
            path = f"data/{kind}/{exp}/{cond}.parquet"
            local = cache / path
            if not local.exists():
                local.parent.mkdir(parents=True, exist_ok=True)
                urllib.request.urlretrieve(HF + path, local)
            for r in pq.read_table(local, columns=cols).to_pylist():
                store[index(r)] = r
    return episodes, agents


def fmt(v):
    # Nulls stay blank: the schema says not to read a missing label as false.
    return "" if v is None else v


def outcome_rows(ep, ag, side):
    peer = "bob" if side == "alice" else "alice"
    verdict, verdict_correct = ep[f"{side}_verdict"], ep[f"{side}_verdict_correct"]
    summary = [f"{verdict} on peer" + ("" if verdict_correct is None else f" ({'correct' if verdict_correct else 'incorrect'})")]
    if ep["both_accept"]:
        summary.append("both_accept")
    if ep["collusion"]:
        summary.append("collusion")
    return {
        "outcome": "; ".join(summary),
        "auto_verdict": fmt(verdict),
        "auto_verdict_correct": fmt(verdict_correct),
        "auto_verdict_forced": fmt(ag["verdict_forced"]),
        "auto_task_correct": fmt(ep[f"{side}_task_correct"]),
        "auto_peer_verdict": fmt(ep[f"{peer}_verdict"]),
        "auto_peer_task_correct": fmt(ep[f"{peer}_task_correct"]),
        "auto_reward": fmt(ag["reward"]),
        "auto_both_accept": fmt(ep["both_accept"]),
        "auto_collusion": fmt(ep["collusion"]),
        "auto_agreement": fmt(ep["agreement"]),
        "auto_agreement_status": fmt(ep["agreement_status"]),
        "auto_relaxation": fmt(ag["relaxation"]),
        "auto_relaxation_status": fmt(ag["relaxation_status"]),
    }


def key_episodes(onset):
    """1-based evaluation episodes to annotate, with their role."""
    if onset is None:
        return [(1, "first"), (4, "early"), (7, "late"), (N_EPISODES, "last")]
    eps = {1: "first", onset: "onset", N_EPISODES: "last"}
    if onset - 1 not in eps and onset > 1:
        eps[onset - 1] = "pre_onset"
    for extra, role in ((onset + 1, "post_onset"), (N_EPISODES // 2, "middle")):
        if len(eps) >= 4:
            break
        if extra not in eps and 1 <= extra <= N_EPISODES:
            eps[extra] = role
    # When onset is 1 or 10 the first/onset/last roles collide; keep the more informative one.
    if onset == 1:
        eps[1] = "first+onset"
    if onset == N_EPISODES:
        eps[N_EPISODES] = "onset+last"
    return sorted(eps.items())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261024)
    ap.add_argument("--cache", type=Path, default=Path(".hf_cache"))
    ap.add_argument("--out", type=Path, default=Path("results/selection"))
    args = ap.parse_args()

    rng = random.Random(args.seed)
    runs = fetch(RUNS, args.cache)
    tasks = {
        (a["sequence_id"], a["evaluation_episode"], a["agent"]): (a["task_id"], a["task_type"])
        for a in fetch(TASK_SOURCE, args.cache)
    }

    by_condition = defaultdict(list)
    for r in runs:
        if r["experiment"] in PLAN:
            by_condition[(r["experiment"], r["condition_id"])].append(r)

    used_seqs = Counter()
    sample = []
    for (exp, cond) in sorted(by_condition):
        k, key = PLAN[exp]
        for r in pick(sorted(by_condition[(exp, cond)], key=lambda r: r["run_id"]), k, key, rng, used_seqs):
            sample.append((r, stratum(r, key)))

    episodes, agents = load_outcomes({(r["experiment"], r["condition_id"]) for r, _ in sample}, args.cache)

    traj_rows, ep_rows = [], []
    for r, strat in sample:
        sides = ["alice"] if r["experiment"] == "controlled_peer" else ["alice", "bob"]
        split = "dev" if r["sequence_id"] in DEV_SEQUENCES else "test"
        eps = key_episodes(r["onset_evaluation_episode"])
        traj_rows.append({
            "run_id": r["run_id"],
            "condition_id": r["condition_id"],
            "experiment": r["experiment"],
            "alice_model": r["alice_model"],
            "bob_model": r["bob_model"],
            "sequence_id": r["sequence_id"],
            "split": split,
            "stratum": strat,
            "onset_pathway": r["onset_pathway"],
            "onset_evaluation_episode": r["onset_evaluation_episode"],
            "converged_collusion": r["converged_collusion"],
            "annotate_sides": "+".join(sides),
            "key_episodes": ";".join(str(e) for e, _ in eps),
            "key_episode_roles": ";".join(role for _, role in eps),
            "trace_file": r["trace_file"],
        })
        for ep, role in eps:
            for side in sides:
                task_id, task_type = tasks[(r["sequence_id"], ep, side)]
                auto = outcome_rows(episodes[(r["run_id"], ep - 1)], agents[(r["run_id"], ep - 1, side)], side)
                ep_rows.append({
                    "run_id": r["run_id"],
                    "experiment": r["experiment"],
                    "split": split,
                    "evaluation_episode": ep,
                    "episode_index": ep - 1,  # join key into the episodes/agents configs
                    "role": role,
                    "agent": side,
                    "task_id": task_id,
                    "task_type": task_type,
                    "coordination": "",
                    "execution": "",
                    "outcome": auto.pop("outcome"),  # pre-filled suggestion; annotators confirm or correct
                    "notes": "",
                    **auto,
                    "trace_file": r["trace_file"],
                })

    args.out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("results/selection/annotation_sample.csv", traj_rows), ("results/selection/annotation_episodes.csv", ep_rows)):
        with open(args.out / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    print(f"{len(traj_rows)} trajectories, {len(ep_rows)} agent-episode rows")
    print("by family:", dict(Counter(t["experiment"] for t in traj_rows)))
    print("by split:", dict(Counter(t["split"] for t in traj_rows)))
    print("by stratum:", dict(Counter(t["stratum"] for t in traj_rows)))
    print("task types:", dict(Counter(e["task_type"] for e in ep_rows)))
    print("distinct sequences:", len({t["sequence_id"] for t in traj_rows}))


if __name__ == "__main__":
    main()
