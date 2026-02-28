#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda command not found. Please install Conda or add it to PATH." >&2
  exit 1
fi

# Initialize conda for this shell and activate project env.
eval "$(conda shell.bash hook)"
conda activate videolingo

python -m batch.utils.channel_auto_pipeline --config batch/channel_auto.yaml
