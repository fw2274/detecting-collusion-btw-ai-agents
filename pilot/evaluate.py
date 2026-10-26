"""Score the LLM labeller against the hand labels and run the distillation pilot.

1. Pooled check: LLM label vs hand label on the eval set (all families together). Accuracy, Cohen's kappa,
   and a 95% interval from a bootstrap that resamples whole runs (episodes in a run are not independent).
2. Pilot labels: the LLM's C1 share per family on the 180-run pilot subset.
3. Distillation: train TF-IDF + logistic regression on the LLM's pilot labels and test it on the hand labels,
   next to the same model trained on the hand labels (run-grouped 5-fold) as the baseline.

Usage:  uv run --with pyarrow --with scikit-learn python pilot/evaluate.py pilot/outputs_qwen3-32b.jsonl
Writes  pilot/labels_<tag>.csv and pilot/metrics_<tag>.json
"""
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, ".")
from build_dm_format import chat  # noqa: E402

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, cohen_kappa_score, confusion_matrix


def parse(raw):
    try:
        d = json.loads(raw)
        return d.get("label") if d.get("label") in ("C1", "C2") else None, d.get("evidence", "")
    except json.JSONDecodeError:
        return None, ""


def boot_kappa(rows, n=2000, seed=0):
    rng = random.Random(seed)
    by_run = defaultdict(list)
    for r in rows:
        by_run[r["run_id"]].append(r)
    runs = list(by_run)
    ks = []
    for _ in range(n):
        sample = [x for rid in (rng.choice(runs) for _ in runs) for x in by_run[rid]]
        y, p = [x["hand"] for x in sample], [x["llm"] for x in sample]
        if len(set(y)) > 1:
            ks.append(cohen_kappa_score(y, p))
    ks.sort()
    return round(ks[int(0.025 * len(ks))], 2), round(ks[int(0.975 * len(ks))], 2)


def text(run_id, ep):
    return " ".join(f"[{m['sender']}] {m['content']}" for m in chat(run_id, ep))


def tfidf_lr():
    return TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True), LogisticRegression(max_iter=3000, class_weight="balanced", C=2)


def main():
    out_path = Path(sys.argv[1])
    tag = out_path.stem.replace("outputs_", "")
    prompts = {json.loads(l)["id"]: json.loads(l) for l in open("pilot/prompts.jsonl", encoding="utf-8")}
    rows = []
    for line in open(out_path, encoding="utf-8"):
        o = json.loads(line)
        p = prompts[o["id"]]
        s, rid, ep = o["id"].split("|")
        lab, ev = parse(o["raw"])
        rows.append({"set": s, "run_id": rid, "ep": int(ep), "family": rid.split("__")[0], "llm": lab, "evidence": ev,
                     "hand": p.get("hand", ""), "annotator": p.get("annotator", "")})
    with open(f"pilot/labels_{tag}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    ev = [r for r in rows if r["set"] == "eval" and r["llm"]]
    y, p = [r["hand"] for r in ev], [r["llm"] for r in ev]
    m = {"model_tag": tag, "parse_failures": sum(1 for r in rows if not r["llm"]),
         "eval": {"n": len(ev), "runs": len({r["run_id"] for r in ev}), "hand_C1": y.count("C1"), "llm_C1": p.count("C1"),
                  "accuracy": round(accuracy_score(y, p), 3), "kappa": round(cohen_kappa_score(y, p), 3),
                  "kappa_95ci_run_bootstrap": boot_kappa(ev),
                  "confusion_hand_rows_C1_C2": confusion_matrix(y, p, labels=["C1", "C2"]).tolist()}}
    for key in ("family", "annotator"):
        m["eval_by_" + key] = {}
        for g in sorted({r[key] for r in ev}):
            sub = [r for r in ev if r[key] == g]
            yy, pp = [r["hand"] for r in sub], [r["llm"] for r in sub]
            m["eval_by_" + key][g] = {"n": len(sub), "accuracy": round(accuracy_score(yy, pp), 2),
                                      "kappa": round(cohen_kappa_score(yy, pp), 2) if len(set(yy + pp)) > 1 else None}

    pil = [r for r in rows if r["set"] == "pilot" and r["llm"]]
    m["pilot"] = {"n": len(pil), "runs": len({r["run_id"] for r in pil}),
                  "C1_share_by_family": {fam: round(sum(r["llm"] == "C1" for r in pil if r["family"] == fam) /
                                                    max(1, sum(r["family"] == fam for r in pil)), 2)
                                         for fam in sorted({r["family"] for r in pil})},
                  "n_by_family": dict(Counter(r["family"] for r in pil))}

    # distillation: train on LLM pilot labels, test on hand labels
    X_tr = [text(r["run_id"], r["ep"]) for r in pil]
    X_te = [text(r["run_id"], r["ep"]) for r in ev]
    v, lr = tfidf_lr()
    lr.fit(v.fit_transform(X_tr), [r["llm"] for r in pil])
    d = list(lr.predict(v.transform(X_te)))
    m["distilled_tfidf_lr"] = {"train": f"{len(pil)} LLM-labelled pilot episodes", "test": f"{len(ev)} hand-labelled",
                               "accuracy": round(accuracy_score(y, d), 3), "kappa": round(cohen_kappa_score(y, d), 3),
                               "agreement_with_llm_on_test": round(accuracy_score(p, d), 3)}
    # baseline: same model trained on hand labels, run-grouped 5-fold
    runs = sorted({r["run_id"] for r in ev})
    rng = random.Random(0)
    rng.shuffle(runs)
    fold = {r: i % 5 for i, r in enumerate(runs)}
    pred = [None] * len(ev)
    for k in range(5):
        tr = [i for i, r in enumerate(ev) if fold[r["run_id"]] != k]
        te = [i for i, r in enumerate(ev) if fold[r["run_id"]] == k]
        v, lr = tfidf_lr()
        lr.fit(v.fit_transform([X_te[i] for i in tr]), [y[i] for i in tr])
        for i, q in zip(te, lr.predict(v.transform([X_te[i] for i in te]))):
            pred[i] = q
    m["hand_trained_tfidf_lr_5fold"] = {"accuracy": round(accuracy_score(y, pred), 3), "kappa": round(cohen_kappa_score(y, pred), 3)}
    meta = out_path.with_name(out_path.stem + "_meta.json")
    if meta.exists():
        m["run"] = json.load(open(meta))
    json.dump(m, open(f"pilot/metrics_{tag}.json", "w"), indent=1)
    print(json.dumps(m, indent=1))


if __name__ == "__main__":
    main()
