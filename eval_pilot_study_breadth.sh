#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}" && pwd)"
cd "${PROJECT_ROOT}"

LOGS_ROOT="./exp/pilot_study_breadth/logs/"
CONFIG="./config/pilot_breadth.json"
OUT_BASE="./exp/pilot_study_breadth/"
QUESTION_DIR="./data/gym_question/"
KEY_POINT_DIR="./deepresearchgym/key_point/"
TIMES=3
BREADTHS=(1 2 4 8) 
CONCURRENCY=16

mkdir -p "${OUT_BASE}"

for d in "${BREADTHS[@]}"; do
  OUT_DIR="${OUT_BASE}/breadth_${d}_1/"
  mkdir -p "${OUT_DIR}"

  echo "=== [GEN] max_breadth=${d} -> ${OUT_DIR} ==="
  time python ./report_generator_batch.py \
      --logs_root "${LOGS_ROOT}" \
      --config "${CONFIG}" \
      --output "${OUT_DIR}" \
      --max_breadth "${d}" \
      --concurrency "${CONCURRENCY}"

  echo "=== [EVAL: quality] breadth ${d} ==="
  { time python -m evaluation.eval_quality_multi_answer \
      --question_dir "${QUESTION_DIR}" \
      --answer_dir "${OUT_DIR}" \
      --output "${OUT_DIR}" \
      --times "${TIMES}"; } \
    2>&1 | tee "${OUT_DIR}/eval_quality_breadth_${d}.log"

  echo "=== [EVAL: citation_recall] breadth ${d} ==="
  { time python -m evaluation.eval_citation_recall_multi_answer \
      --question_dir "${QUESTION_DIR}" \
      --answer_dir "${OUT_DIR}" \
      --output "${OUT_DIR}" \
      --times "${TIMES}"; } \
    2>&1 | tee "${OUT_DIR}/eval_citation_recall_breadth_${d}.log"

  echo "=== [EVAL: kpr] breadth ${d} ==="
  { time python -m evaluation.eval_kpr_multi_answer \
      --question_dir "${QUESTION_DIR}" \
      --answer_dir "${OUT_DIR}" \
      --output "${OUT_DIR}" \
      --key_point_dir "${KEY_POINT_DIR}" \
      --times "${TIMES}"; } \
    2>&1 | tee "${OUT_DIR}/eval_kpr_breadth_${d}.log"

done

echo "All done. Logs are stored in each breadth_* directory."