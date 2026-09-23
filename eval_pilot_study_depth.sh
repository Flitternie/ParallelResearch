#!/usr/bin/env bash
# ADOBE CONFIDENTIAL
#
# Copyright 2026 Adobe
# All Rights Reserved.
#
# NOTICE: All information contained herein is, and remains
# the property of Adobe and its suppliers, if any. The intellectual
# and technical concepts contained herein are proprietary to Adobe
# and its suppliers and are protected by all applicable intellectual
# property laws, including trade secret and copyright laws.
# Dissemination of this information or reproduction of this material
# is strictly forbidden unless prior written permission is obtained
# from Adobe.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}" && pwd)"
cd "${PROJECT_ROOT}"

LOGS_ROOT="./exp/pilot_study_depth/logs/"
CONFIG="./config/pilot_depth.json"
OUT_BASE="./exp/pilot_study_depth/"
QUESTION_DIR="./data/gym_question/"
KEY_POINT_DIR="./deepresearchgym/key_point/"
TIMES=3
DEPTHS=(1 2 3 4 5)
CONCURRENCY=16

mkdir -p "${OUT_BASE}"

for d in "${DEPTHS[@]}"; do
  OUT_DIR="${OUT_BASE}/depth_${d}/"
  mkdir -p "${OUT_DIR}"

  echo "=== [GEN] max_depth=${d} -> ${OUT_DIR} ==="
  time python ./report_generator_batch.py \
      --logs_root "${LOGS_ROOT}" \
      --config "${CONFIG}" \
      --output "${OUT_DIR}" \
      --max_depth "${d}" \
      --concurrency "${CONCURRENCY}"

  echo "=== [EVAL: quality] depth ${d} ==="
  { time python -m evaluation.eval_quality_multi_answer \
      --question_dir "${QUESTION_DIR}" \
      --answer_dir "${OUT_DIR}" \
      --output "${OUT_DIR}" \
      --times "${TIMES}"; } \
    2>&1 | tee "${OUT_DIR}/eval_quality_depth_${d}.log"

  echo "=== [EVAL: citation_recall] depth ${d} ==="
  { time python -m evaluation.eval_citation_recall_multi_answer \
      --question_dir "${QUESTION_DIR}" \
      --answer_dir "${OUT_DIR}" \
      --output "${OUT_DIR}" \
      --times "${TIMES}"; } \
    2>&1 | tee "${OUT_DIR}/eval_citation_recall_depth_${d}.log"

  echo "=== [EVAL: kpr] depth ${d} ==="
  { time python -m evaluation.eval_kpr_multi_answer \
      --question_dir "${QUESTION_DIR}" \
      --answer_dir "${OUT_DIR}" \
      --output "${OUT_DIR}" \
      --key_point_dir "${KEY_POINT_DIR}" \
      --times "${TIMES}"; } \
    2>&1 | tee "${OUT_DIR}/eval_kpr_depth_${d}.log"

done

echo "All done. Logs are stored in each depth_* directory."
