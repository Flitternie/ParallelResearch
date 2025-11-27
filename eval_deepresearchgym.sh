#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}" && pwd)"
cd "${PROJECT_ROOT}"

QUESTION_DIR="./data/gym_question/"
KEY_POINT_DIR="./deepresearchgym/key_point/"
TIMES=5
METHODS=("gym_time_2_baseline" "gym_time_2_ablation" "gym_time_2_flashresearch" "gym_time_10_baseline" "gym_time_10_ablation" "gym_time_10_flashresearch")
CONCURRENCY=64

export OPENAI_API_KEY=$(cat ./keys/openai.key)
export OPENAI_BASE_URL=$(cat ./keys/openai_url.key)

for method in "${METHODS[@]}"; do
  OUT_DIR="./exp/${method}/"

  # Check if the method directory exists
  if [ ! -d "${OUT_DIR}" ]; then
    echo "Warning: Directory ${OUT_DIR} does not exist. Skipping ${method}."
    continue
  fi

  echo "=== [EVAL: quality] ${method} ==="
  { time python -m evaluation.eval_quality_multi_answer \
      --question_dir "${QUESTION_DIR}" \
      --answer_dir "${OUT_DIR}" \
      --output "${OUT_DIR}/results/" \
      --times "${TIMES}"; } \
    2>&1 | tee "${OUT_DIR}/eval_quality_${method}.log"

  echo "=== [EVAL: citation_recall] ${method} ==="
  { time python -m evaluation.eval_citation_recall_multi_answer \
      --question_dir "${QUESTION_DIR}" \
      --answer_dir "${OUT_DIR}" \
      --output "${OUT_DIR}/results/" \
      --times "${TIMES}"; } \
    2>&1 | tee "${OUT_DIR}/eval_citation_recall_${method}.log"

  echo "=== [EVAL: kpr] ${method} ==="
  { time python -m evaluation.eval_kpr_multi_answer \
      --question_dir "${QUESTION_DIR}" \
      --answer_dir "${OUT_DIR}" \
      --output "${OUT_DIR}/results/" \
      --key_point_dir "${KEY_POINT_DIR}" \
      --times "${TIMES}"; } \
    2>&1 | tee "${OUT_DIR}/eval_kpr_${method}.log"

done

echo "All done. Logs are stored in each method directory."