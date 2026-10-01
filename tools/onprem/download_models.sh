#!/usr/bin/env bash
# 온프레미스 라우터 비교용 로컬 모델 다운로드(1회). 이후 측정은 HF_HUB_OFFLINE=1로 돈다.
set -e
source ~/vllm-venv/bin/activate
python -c "import vllm; print('vllm', vllm.__version__)"
for m in Qwen/Qwen2.5-3B-Instruct Qwen/Qwen2.5-7B-Instruct-AWQ; do
  echo "== $m"
  python -c "from huggingface_hub import snapshot_download as s; print(s('$m', allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.tiktoken']))"
done
du -sh ~/.cache/huggingface/hub/models--Qwen--*
echo DOWNLOAD_DONE
