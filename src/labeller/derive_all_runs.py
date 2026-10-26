"""Derive the run metrics for every in-scope run from the predicted episode labels, using the same definitions
as the hand files (build_dm_format.derive_run), then check them against the 30 fully hand-labelled runs.

collude = 1 for C3, C5a and C5. The check uses held-out predictions (each hand run's episodes were predicted by a
model that never saw that run), so it is a fair test.

Usage:  uv run --with pandas python src/labeller/derive_all_runs.py
Writes  results/final_labels/runs_labelled.csv, results/final_labels/runs_derived_check.csv
(build_report.py calls build_runs and check_runs itself, so running it is enough.)
"""
import sys

import pandas as pd

sys.path.insert(0, "src")
from build_dm_format import derive_run  # noqa: E402

COLLUDE = {"C3", "C5", "C5a"}
METRICS = ["final_collude_hand", "n_episodes_collude_hand", "intensity", "intensity_level", "onset_episode", "gaps_pct",
           "reentry", "reentry_lags", "ended_early", "longest_streak", "n_breaks", "overview_group",
           "n_C1", "n_C2", "n_C3", "n_C4", "n_C5", "n_C5a"]


def derive(df, col):
    rows = []
    for rid, g in df.sort_values("evaluation_episode").groupby("run_id", sort=True):
        cats = list(g[col])
        r = {"run_id": rid, "sequence": " ".join(cats)}
        r.update(derive_run([int(c in COLLUDE) for c in cats], cats))
        rows.append(r)
    return pd.DataFrame(rows)


def build_runs(eps, ladder_runs):
    """One row per run: ids, the 10-episode label sequence, derived metrics, category counts, ladder."""
    meta = eps.groupby("run_id").agg(family=("family", "first"), condition_id=("condition_id", "first"),
                                     n_episodes=("category", "size")).reset_index()
    runs = meta.merge(derive(eps, "category"), on="run_id").merge(ladder_runs[["run_id", "ladder"]], on="run_id")
    runs = runs[["run_id", "family", "condition_id", "n_episodes", "sequence", *METRICS, "ladder"]]
    return runs.rename(columns={"final_collude_hand": "final_collude", "n_episodes_collude_hand": "n_episodes_collude"})


def check_runs(pred_path="results/labeller/labeler/llm_heldout_predictions.csv", col="llm_only"):
    """Derived metrics from held-out predictions vs hand labels on the fully hand-labelled runs."""
    pred = pd.read_csv(pred_path)
    full = pred.groupby("run_id").filter(lambda g: len(g) == 10)
    h, p = derive(full, "code").set_index("run_id"), derive(full, col).set_index("run_id")
    return pd.DataFrame([{"metric": m, "runs": len(h), "match": int((h[m].astype(str) == p[m].astype(str)).sum()),
                          "match_rate": round((h[m].astype(str) == p[m].astype(str)).mean(), 2)} for m in METRICS])


def main():
    eps = pd.read_csv("results/final_labels/episodes_labelled.csv")
    runs = build_runs(eps, pd.read_csv("results/labeller/labeler/llm_ladder_runs.csv"))
    runs.to_csv("results/final_labels/runs_labelled.csv", index=False)
    check = check_runs()
    check.to_csv("results/final_labels/runs_derived_check.csv", index=False)
    print(f"{len(runs)} runs; all have 10 episodes: {bool((runs.n_episodes == 10).all())}")
    print(check.to_string(index=False))


if __name__ == "__main__":
    main()
