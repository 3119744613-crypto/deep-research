#!/bin/sh
# 只启动通用文档研发服务；不会启动或修改原平台服务。
set -eu

if [ "$#" -lt 2 ]; then
  echo "用法: DOCUMENT_RESEARCH_PYTHON=/path/to/python $0 init|start /absolute/data-dir [port]" >&2
  exit 2
fi

operation=$1
data_dir=$2
port=${3:-4198}
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_bin=${DOCUMENT_RESEARCH_PYTHON:-python3}
cd "$repo_dir"

case "$operation" in
  init) exec "$python_bin" -m document_research --data-dir "$data_dir" --init ;;
  start) exec "$python_bin" -m document_research --data-dir "$data_dir" --port "$port" ;;
  *) echo "未知操作；仅支持 init 或 start。" >&2; exit 2 ;;
esac
