"""OpenAI-compatible vLLM server on Modal for Colosseum/Terrarium runs.

Serves Qwen2.5-7B-Instruct, the local model in Colosseum's collusion configs.

Deploy:  modal deploy modal/vllm_server.py
Stop:    modal app stop colosseum-vllm

Terrarium's vLLM client health-checks GET /v1/models without auth, so the
server runs without --api-key. Exposure is limited instead: one container at
most, scaled to zero after SCALEDOWN_MINUTES idle. Stop the app when done.
"""

import subprocess

import modal

MODEL = "Qwen/Qwen2.5-7B-Instruct"
PORT = 8000
MAX_MODEL_LEN = 16000
SCALEDOWN_MINUTES = 10

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("vllm==0.10.2", "transformers==4.57.1", "huggingface_hub[hf_transfer]")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

hf_cache = modal.Volume.from_name("colosseum-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("colosseum-vllm-cache", create_if_missing=True)

app = modal.App("colosseum-vllm")


@app.function(
    image=image,
    gpu="A10G",
    max_containers=1,
    scaledown_window=SCALEDOWN_MINUTES * 60,
    timeout=4 * 60 * 60,
    volumes={"/root/.cache/huggingface": hf_cache, "/root/.cache/vllm": vllm_cache},
)
@modal.concurrent(max_inputs=32)
@modal.web_server(port=PORT, startup_timeout=15 * 60)
def serve():
    cmd = [
        "vllm", "serve", MODEL,
        "--served-model-name", MODEL,
        "--host", "0.0.0.0",
        "--port", str(PORT),
        "--max-model-len", str(MAX_MODEL_LEN),
        "--gpu-memory-utilization", "0.9",
        "--enable-auto-tool-choice",
        "--tool-call-parser", "hermes",
    ]
    subprocess.Popen(cmd)
