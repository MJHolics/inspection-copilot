#!/usr/bin/env bash
# 로컬 vLLM 서버(OpenAI 호환) — 폐쇄망 조건: HF_HUB_OFFLINE=1로 허브 접근 없이 로컬 캐시만 쓴다.
# 사용: bash serve.sh Qwen/Qwen2.5-1.5B-Instruct [추가 인자...]
set -e
source ~/vllm-venv/bin/activate
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export VLLM_WSL2_ENABLE_PIN_MEMORY=1 VLLM_USE_FLASHINFER_SAMPLER=0
MODEL="$1"; shift
exec vllm serve "$MODEL" --port 8000 --max-model-len 4096 --gpu-memory-utilization 0.85 "$@"
