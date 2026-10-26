"""Write a compact per-trajectory digest (messages, verdicts, judge labels, trimmed reasoning) for annotation.

Usage:  uv run --with pyarrow python make_digests.py [selection_50.csv]  -> digests/<batch>_<run_id>.md
"""
import csv
import gzip
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

DATA = Path("hf_data")


def reasoning_text(rt):
    if not rt:
        return ""
    if isinstance(rt, str):
        return rt
    for k in ("reasoning_content", "text", "summary", "content"):
        if isinstance(rt.get(k), str) and rt[k]:
            return rt[k]
    raw = json.dumps(rt)
    # Gemini thought signatures and OpenAI encrypted reasoning carry no readable text.
    if "encrypted_content" in raw or "thought_signature" in raw:
        return "[not readable: provider returned encrypted reasoning]"
    return raw


def trim(s, head, tail):
    s = (s or "").strip()
    if len(s) <= head + tail + 20:
        return s
    return s[:head] + " [...]" + (" " + s[-tail:] if tail else "")


def main():
    sel = list(csv.DictReader(open(sys.argv[1] if len(sys.argv) > 1 else "selection_50.csv", encoding="utf-8")))
    out = Path("digests")
    out.mkdir(exist_ok=True)
    cache = {}
    for s in sel:
        key = (s["experiment"], s["condition_id"])
        if key not in cache:
            ep = pq.read_table(DATA / f"data/episodes/{key[0]}/{key[1]}.parquet",
                               columns=["run_id", "episode_index", "collusion", "both_accept", "agreement", "agreement_status"]).to_pylist()
            ag = pq.read_table(DATA / f"data/agents/{key[0]}/{key[1]}.parquet",
                               columns=["run_id", "episode_index", "agent", "relaxation", "relaxation_status"]).to_pylist()
            cache[key] = ({(e["run_id"], e["episode_index"]): e for e in ep},
                          {(a["run_id"], a["episode_index"], a["agent"]): a for a in ag})
        E, A = cache[key]
        t = json.load(gzip.open(DATA / s["trace_file"], "rt", encoding="utf-8"))
        lines = [f"# {s['run_id']}  (batch {s['batch']})",
                 f"models: alice={s['alice_model']} bob={s['bob_model']} | dataset onset={s['onset_evaluation_episode']} pathway={s['onset_pathway']} converged={s['converged_collusion']}"]
        for e in t["results"]:
            i = e["episode_index"]
            ed = E[(s["run_id"], i)]
            lines.append(f"\n## Ep {e['evaluation_episode']} [{e['task_type']}] collusion={ed['collusion']} both_accept={ed['both_accept']} agreement={ed['agreement']}")
            for side in ("alice", "bob"):
                a = e["agents"][side]
                rl = A[(s["run_id"], i, side)]
                lines.append(f"- {side}: own_work_should_be={a['true_expected_verdict']} verdict_on_peer={a['verdict']} correct={a['verdict_correct']} forced={a.get('verdict_forced')} relaxation={rl['relaxation']}")
            for m in e["channel_transcript"]:
                lines.append(f"  r{m['round']} {m['sender'][0].upper()}: {m['content']}")
            for side in ("alice", "bob"):
                vr = [x for x in e["llm_reasoning_traces"] if x["agent_id"] == side and x["phase"] == "verdict"]
                if vr:
                    lines.append(f"  [{side} verdict reasoning] {trim(reasoning_text(vr[-1]['reasoning_trace']), 250, 450)}")
                lines.append(f"  [{side} reflection] {trim(e['agents'][side].get('reflection'), 300, 0)}")
        (out / f"b{s['batch']}_{s['run_id']}.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote", len(sel), "digests")


if __name__ == "__main__":
    main()
