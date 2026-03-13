#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: .env file not found at $ENV_FILE"
  echo "cp .env.example .env and fill it out"
  exit 1
fi

echo "Loading environment variables from .env..."
set -a
source "$ENV_FILE"
set +a

# Optional: keep this guard so you don't accidentally use the placeholder:
if [ "$MODEL_PATH" = "/your/model/path" ] || [ -z "$MODEL_PATH" ]; then
  echo "Error: MODEL_PATH not configured in .env (set it to your OpenRouter model id, e.g., alibaba/tongyi-deepresearch-30b-a3b)"
  exit 1
fi

#####################################
### OpenRouter mode: no vLLM servers
#####################################
echo "OpenRouter mode: skipping local vLLM servers & port checks."

#####################################
### 3. start infer
#####################################
echo "==== start infer... ===="
cd "$SCRIPT_DIR"

python -u run_multi_react.py \
  --dataset "$DATASET" \
  --output "$OUTPUT_PATH" \
  --max_workers $MAX_WORKERS \
  --model "$MODEL_PATH" \
  --temperature $TEMPERATURE \
  --presence_penalty $PRESENCE_PENALTY \
  --total_splits ${WORLD_SIZE:-1} \
  --worker_split $((${RANK:-0} + 1)) \
  --roll_out_count $ROLLOUT_COUNT
