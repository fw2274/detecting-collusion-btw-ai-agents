"""Build the classifier-labelling report (HTML) and the final labelled CSVs from the training outputs.

Inputs (made by pilot/train_labeler.py, pilot/evaluate.py and pilot/summarise_all.py):
  pilot/labeler/{,llm_,llm_llmtrain_}heldout.json, pilot/labeler/llm_heldout_predictions.csv,
  pilot/labeler/llm_all_episodes_predicted.csv, pilot/labeler/llm_ladder_runs.csv,
  pilot/metrics_qwen3-32b.json, pilot/all_metrics_qwen3-32b.json
Outputs:
  final_labels/episodes_labelled.csv, final_labels/runs_labelled.csv, reports/classifier_labeling.html

Usage:  uv run --with pandas python pilot/build_report.py
"""
import html
import json
import os
import shutil

import sys

import pandas as pd

sys.path.insert(0, "pilot")
from derive_all_runs import build_runs, check_runs  # noqa: E402

L = "pilot/labeler"
FAMILY = {"main": "Main", "cross_model": "Cross-model", "feedback": "Feedback", "memory_length": "Memory length",
          "memory_scope": "Memory scope", "reward_scope": "Reward scope", "reward_type": "Reward type", "warmup": "Warm-up"}
ORDER = ["C1", "C2", "C2s", "C3", "C5a", "C5", "C4"]
CAT = {"C1": "C1 legitimate coordination", "C2": "C2 no coordination, both reject", "C2s": "C2s no coordination, split",
       "C3": "C3 collusion carried out", "C4": "C4 talk only", "C5": "C5 tacit collusion", "C5a": "C5a one-sided commitment"}


def j(p):
    return json.load(open(p, encoding="utf-8"))


def table(head, rows, cls=""):
    h = "".join(f"<th>{html.escape(str(x))}</th>" for x in head)
    b = "".join("<tr>" + "".join(f"<td>{x}</td>" for x in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def f2(x):
    return "—" if x is None else f"{x:.2f}"


def bars(rows, best):
    """Horizontal paired bars, accuracy and kappa, one row per variant, drawn to one 0-1 scale."""
    W, lab_w, row_h, top = 640, 250, 46, 30
    plot_w = W - lab_w - 50
    H = top + row_h * len(rows) + 30
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Accuracy and kappa by variant" class="chart">']
    for t in (0, 0.2, 0.4, 0.6, 0.8, 1.0):
        x = lab_w + t * plot_w
        out.append(f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" y2="{H - 24}" class="grid"/>'
                   f'<text x="{x:.1f}" y="{H - 8}" class="tick" text-anchor="middle">{t:.1f}</text>')
    for i, (name, acc, kap) in enumerate(rows):
        y = top + i * row_h
        weight = ' font-weight="600"' if name == best else ""
        out.append(f'<text x="{lab_w - 10}" y="{y + 17}" class="lab" text-anchor="end"{weight}>{html.escape(name)}</text>')
        for k, (v, c) in enumerate(((acc, "acc"), (kap, "kap"))):
            yy = y + 4 + k * 15
            w = max(0, v) * plot_w
            out.append(f'<rect x="{lab_w}" y="{yy}" width="{w:.1f}" height="12" rx="2" class="{c}"/>'
                       f'<text x="{lab_w + w + 5:.1f}" y="{yy + 10}" class="val">{v:.2f}</text>')
    out.append(f'<g transform="translate({lab_w},{12})"><rect width="12" height="10" rx="2" class="acc"/>'
               f'<text x="17" y="9" class="tick">accuracy</text><rect x="92" width="12" height="10" rx="2" class="kap"/>'
               f'<text x="109" y="9" class="tick">Cohen\'s κ</text></g></svg>')
    return "".join(out)


def main():
    hand = j(f"{L}/heldout.json")
    feat = j(f"{L}/llm_heldout.json")
    trn = j(f"{L}/llm_llmtrain_heldout.json")
    pilot = j("pilot/metrics_qwen3-32b.json")
    full = j("pilot/all_metrics_qwen3-32b.json")
    pred = pd.read_csv(f"{L}/llm_heldout_predictions.csv")
    eps = pd.read_csv(f"{L}/llm_all_episodes_predicted.csv")
    runs = pd.read_csv(f"{L}/llm_ladder_runs.csv")
    best = feat["used"]

    os.makedirs("final_labels", exist_ok=True)
    eps["collude"] = eps.category.isin(["C3", "C5", "C5a"]).astype(int)
    eps = eps.rename(columns={"llm": "llm_label"})
    eps.to_csv("final_labels/episodes_labelled.csv", index=False)
    runs = build_runs(eps, runs)
    runs.to_csv("final_labels/runs_labelled.csv", index=False)
    check = check_runs()
    check.to_csv("final_labels/runs_derived_check.csv", index=False)

    # evaluation rows: (display name, what it is, scores)
    ev = [("Dataset fields only", "Verdicts and the agreement judge; no chat reading", feat["baseline"]),
          ("Classifier, hand labels", "Rule on both-accept; TF-IDF + LR on both-reject, trained on hand labels", hand["model_c3rule"]),
          ("Classifier + LLM feature", "Same, with the LLM's C1/C2 label added as an input", feat["model_c3rule"]),
          ("Classifier + LLM training labels", "Same, also trained on LLM-labelled episodes from unlabelled runs", trn["model_c3rule"]),
          ("Rule + LLM label", "Rule on both-accept; the LLM's label used directly on both-reject", feat["llm_only"])]
    best_name = {"llm_only": "Rule + LLM label", "model_c3rule": "Classifier + LLM feature"}.get(best, best)
    ev_rows = [[f"<b>{n}</b>" if n == best_name else n, d, f2(s["accuracy"]), f2(s["kappa"]),
                f2(s["accept_branch_kappa"]), f2(s["reject_branch_kappa"]), f2(s["C3_recall"])] for n, d, s in ev]
    chart = bars([(n, s["accuracy"], s["kappa"]) for n, _, s in ev], best_name)
    # both-reject only: accuracy from each run's held-out predictions, kappa from the reports
    def rej_acc(file, col):
        d = pd.read_csv(f"{L}/{file}").merge(eps[["run_id", "evaluation_episode", "branch"]], on=["run_id", "evaluation_episode"])
        d = d[d.branch == "both_reject"]  # same 108 episodes as reject_branch_kappa
        return float((d.code == d[col]).mean())
    files = ["llm_heldout_predictions.csv", "heldout_predictions.csv", "llm_heldout_predictions.csv",
             "llm_llmtrain_heldout_predictions.csv", "llm_heldout_predictions.csv"]
    cols = ["baseline", "model_c3rule", "model_c3rule", "model_c3rule", "llm_only"]
    chart2 = bars([(n, rej_acc(f, c), s["reject_branch_kappa"] or 0) for (n, _, s), f, c in zip(ev, files, cols)], best_name)

    # sample: hand labels by family and class
    ct = pd.crosstab(pred.family, pred.code).reindex(columns=ORDER, fill_value=0)
    fam_runs = pred.groupby("family").run_id.nunique()
    data_eps = eps.groupby("family").size()
    data_runs = eps.groupby("family").run_id.nunique()
    samp_rows = []
    for f in FAMILY:
        if f not in data_eps:
            continue
        r = ct.loc[f] if f in ct.index else pd.Series(0, index=ORDER)
        samp_rows.append([FAMILY[f], int(fam_runs.get(f, 0)), int(r.sum()), *[int(r[c]) for c in ORDER],
                          f"{int(data_runs[f]):,}", f"{int(data_eps[f]):,}"])
    tot = ct.sum()
    samp_rows.append(["<b>Total</b>", f"<b>{pred.run_id.nunique()}</b>", f"<b>{len(pred)}</b>", *[f"<b>{int(tot[c])}</b>" for c in ORDER],
                      f"<b>{eps.run_id.nunique():,}</b>", f"<b>{len(eps):,}</b>"])

    # held-out accuracy by family for the variant used
    fam_rows = []
    for f in FAMILY:
        s = pred[pred.family == f]
        if len(s) == 0:
            continue
        rej = s[s.code.isin(["C1", "C2"])]
        fam_rows.append([FAMILY[f], len(s), f2((s.code == s[best]).mean()), len(rej),
                         f2((rej.code == rej[best]).mean()) if len(rej) else "—"])

    # final labelled outcome
    out_ct = pd.crosstab(eps.family, eps.category).reindex(columns=ORDER, fill_value=0)
    out_rows = [[FAMILY[f], *[f"{int(out_ct.loc[f, c]):,}" for c in ORDER], f"{int(out_ct.loc[f].sum()):,}"]
                for f in FAMILY if f in out_ct.index]
    t = out_ct.sum()
    out_rows.append(["<b>Total</b>", *[f"<b>{int(t[c]):,}</b>" for c in ORDER], f"<b>{int(t.sum()):,}</b>"])
    src = eps.label_source.value_counts()
    src_rows = [[html.escape(k), f"{v:,}", f"{v / len(eps):.0%}"] for k, v in src.items()]
    lad = runs.ladder.value_counts().reindex([0, 1, 2, 3, 4], fill_value=0)
    lad_names = {0: "0 · no evidence", 1: "1 · talk only (C4)", 2: "2 · tacit conduct (C5)",
                 3: "3 · one-sided commitment (C5a)", 4: "4 · explicit deal (C3)"}
    lad_rows = [[lad_names[k], f"{v:,}", f"{v / len(runs):.0%}"] for k, v in lad.items()]

    # run-level results
    num = runs.assign(**{c: pd.to_numeric(runs[c]) for c in ("onset_episode", "gaps_pct", "reentry", "ended_early")})
    any_c = runs.n_episodes_collude > 0
    col_rows = [["Colluded in at least one episode", f"{int(any_c.sum()):,}", f"{any_c.mean():.0%}"],
                ["Never colluded", f"{int((~any_c).sum()):,}", f"{(~any_c).mean():.0%}"],
                ["Colluded in the final episode", f"{int(runs.final_collude.sum()):,}", f"{runs.final_collude.mean():.0%}"],
                ["High intensity (7 or more of 10 episodes)", f"{int((runs.intensity_level == 'high').sum()):,}",
                 f"{(runs.intensity_level == 'high').mean():.0%}"]]
    rf_rows = []
    for f in FAMILY:
        g = num[num.family == f]
        if not len(g):
            continue
        m = lambda c: "—" if g[c].isna().all() else f"{g[c].mean():.2f}"
        rf_rows.append([FAMILY[f], len(g), f"{(g.n_episodes_collude > 0).mean():.0%}", f"{g.intensity.mean():.2f}",
                        m("onset_episode"), m("gaps_pct"), m("reentry"), m("ended_early"), f"{g.final_collude.mean():.0%}"])
    ov = runs.overview_group.value_counts()
    ov_rows = [[html.escape(k), f"{v:,}", f"{v / len(runs):.0%}"] for k, v in ov.items()]
    lv = runs.intensity_level.value_counts().reindex(["none", "low", "medium", "high"], fill_value=0)
    lv_rows = [[k, f"{v:,}", f"{v / len(runs):.0%}"] for k, v in lv.items()]
    ck_names = {"final_collude_hand": "final collusion", "n_episodes_collude_hand": "episodes colluded", "intensity": "intensity",
                "intensity_level": "intensity level", "onset_episode": "onset episode", "gaps_pct": "gaps %",
                "reentry": "re-entry count", "reentry_lags": "re-entry lags", "ended_early": "ended early",
                "longest_streak": "longest streak", "n_breaks": "breaks", "overview_group": "overview group"}
    ck_rows = [[ck_names.get(r.metric, r.metric), f"{r.match} / {r.runs}", f"{r.match_rate:.2f}"] for r in check.itertuples()]

    pe = pilot["eval"]
    fr = full.get("run", {})
    cost = fr.get("gpu_seconds", 0) / 3600 * 3.95
    page = TEMPLATE.format(
        n_hand=len(pred), n_runs=pred.run_id.nunique(), n_eps=f"{len(eps):,}", n_all_runs=f"{eps.run_id.nunique():,}",
        best_name=best_name, best_acc=f2(feat[best]["accuracy"]), best_kap=f2(feat[best]["kappa"]),
        best_rej=f2(feat[best]["reject_branch_kappa"]), best_acc_k=f2(feat[best]["accept_branch_kappa"]),
        n_acc=feat[best]["accept_branch_n"], n_rej=feat[best]["reject_branch_n"], n_split=len(pred) - feat[best]["accept_branch_n"] - feat[best]["reject_branch_n"],
        sample=table(["Family", "Runs", "Episodes", *ORDER, "Dataset runs", "Dataset episodes"], samp_rows, "num"),
        evaluation=table(["Variant", "What it does", "Accuracy", "κ", "Both-accept κ", "Both-reject κ", "C3 recall"], ev_rows, "num ev"),
        chart=chart, chart2=chart2,
        family=table(["Family", "Held-out episodes", "Accuracy", "Both-reject episodes", "Both-reject accuracy"], fam_rows, "num"),
        outcome=table(["Family", *ORDER, "Total"], out_rows, "num"),
        sources=table(["Where the label comes from", "Episodes", "Share"], src_rows, "num"),
        ladder=table(["Run ladder level", "Runs", "Share"], lad_rows, "num"),
        run_collude=table(["Runs", "Count", "Share"], col_rows, "num"),
        run_family=table(["Family", "Runs", "Colluded at all", "Intensity", "Onset ep", "Gaps %", "Re-entry", "Ended early",
                          "Colluded at end"], rf_rows, "num"),
        run_overview=table(["Overview group", "Runs", "Share"], ov_rows, "num"),
        run_level=table(["Intensity level", "Runs", "Share"], lv_rows, "num"),
        run_check=table(["Run metric", "Matches hand labels", "Rate"], ck_rows, "num"),
        n_full=int(check.runs.iloc[0]),
        p_n=pe["n"], p_runs=pe["runs"], p_acc=f2(pe["accuracy"]), p_kap=f2(pe["kappa"]),
        p_lo=f2(pe["kappa_95ci_run_bootstrap"][0]), p_hi=f2(pe["kappa_95ci_run_bootstrap"][1]),
        f_n=f"{full['n']:,}", f_c1=f"{full['C1_share']:.0%}", f_fail=full["parse_failures"],
        f_min=f"{fr.get('wall_seconds', 0) / 60:.0f}", f_cost=f"{cost:.0f}",
        rej_kap_hand=f2(hand["model_c3rule"]["reject_branch_kappa"]),
    )
    os.makedirs("reports", exist_ok=True)
    open("reports/classifier_labeling.html", "w", encoding="utf-8").write(page)
    print("wrote reports/classifier_labeling.html, final_labels/episodes_labelled.csv, final_labels/runs_labelled.csv")
    print("best:", best, feat[best])


TEMPLATE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_template.html"), encoding="utf-8").read()

if __name__ == "__main__":
    main()
