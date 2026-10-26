"""Batch LLM labeller on Modal for subtask A (C1 vs C2), using vLLM offline inference.

Default setup: Qwen/Qwen3-32B-FP8 on one H100 (80 GB). FP8 weights are ~33 GB, which leaves room for a
large KV cache. The few-shot prefix is shared by every prompt, so vLLM's prefix caching computes it once.
Thinking is disabled, decoding is greedy, and output is constrained to the JSON schema below.

Run:   modal run modal/labeller.py --infile pilot/prompts.jsonl --outfile pilot/outputs_qwen3-32b.jsonl
Other: modal run modal/labeller.py --model Qwen/Qwen3-8B --gpu L40S --outfile pilot/outputs_qwen3-8b.jsonl
Full:  modal run modal/labeller.py --infile pilot/prompts_all.jsonl --outfile pilot/outputs_all_qwen3-32b.jsonl --shards 4
       (--shards N splits the prompts across N containers that run in parallel, one GPU each)
No web endpoint is exposed; the container exits when the batch is done.
"""
import json
import time

import modal

MODEL = "Qwen/Qwen3-32B-FP8"
GPU = "H100"
MAX_MODEL_LEN = 8192
SCHEMA = {
    "type": "object",
    "properties": {"label": {"type": "string", "enum": ["C1", "C2"]}, "evidence": {"type": "string", "maxLength": 300}},
    "required": ["label", "evidence"],
}

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("vllm==0.10.2", "transformers==4.57.1", "huggingface_hub[hf_transfer]")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)
hf_cache = modal.Volume.from_name("colosseum-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("colosseum-vllm-cache", create_if_missing=True)
app = modal.App("salt-c1c2-labeller")


@app.function(image=image, gpu=GPU, timeout=2 * 60 * 60,
              volumes={"/root/.cache/huggingface": hf_cache, "/root/.cache/vllm": vllm_cache})
def label(prompts: list[dict], model: str = MODEL) -> dict:
    from vllm import LLM, SamplingParams
    from vllm.sampling_params import GuidedDecodingParams

    t0 = time.time()
    llm = LLM(model=model, max_model_len=MAX_MODEL_LEN, gpu_memory_utilization=0.92, enable_prefix_caching=True)
    t_load = time.time() - t0
    params = SamplingParams(temperature=0.0, max_tokens=200, guided_decoding=GuidedDecodingParams(json=SCHEMA))
    t1 = time.time()
    outs = llm.chat([p["messages"] for p in prompts], params, chat_template_kwargs={"enable_thinking": False})
    t_gen = time.time() - t1
    rows = []
    for p, o in zip(prompts, outs):
        rows.append({"id": p["id"], "raw": o.outputs[0].text,
                     "prompt_tokens": len(o.prompt_token_ids), "output_tokens": len(o.outputs[0].token_ids)})
    hf_cache.commit()
    return {"rows": rows, "model": model, "load_seconds": round(t_load, 1), "generate_seconds": round(t_gen, 1)}


@app.local_entrypoint()
def main(infile: str = "pilot/prompts.jsonl", outfile: str = "pilot/outputs.jsonl", model: str = MODEL, gpu: str = GPU,
         shards: int = 1):
    prompts = [json.loads(line) for line in open(infile, encoding="utf-8")]
    fn = label if gpu == GPU else label.with_options(gpu=gpu)
    t0 = time.time()
    items = [{"id": p["id"], "messages": p["messages"]} for p in prompts]
    parts = [items[i::shards] for i in range(shards)]
    outs = list(fn.map(parts, kwargs={"model": model}))
    wall = time.time() - t0
    res = {"rows": [r for o in outs for r in o["rows"]], "model": model, "shards": shards,
           "load_seconds": max(o["load_seconds"] for o in outs), "generate_seconds": max(o["generate_seconds"] for o in outs),
           "gpu_seconds": round(sum(o["load_seconds"] + o["generate_seconds"] for o in outs), 1)}
    with open(outfile, "w", encoding="utf-8") as f:
        for r in res["rows"]:
            f.write(json.dumps(r) + "\n")
    meta = {k: v for k, v in res.items() if k != "rows"} | {"gpu": gpu, "wall_seconds": round(wall, 1), "n": len(res["rows"]),
                                                           "prompt_tokens": sum(r["prompt_tokens"] for r in res["rows"]),
                                                           "output_tokens": sum(r["output_tokens"] for r in res["rows"])}
    json.dump(meta, open(outfile.replace(".jsonl", "_meta.json"), "w"), indent=1)
    print(json.dumps(meta))
