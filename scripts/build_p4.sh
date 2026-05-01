#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
P4_SRC="${ROOT_DIR}/p4/main.p4"
OUT_DIR="${ROOT_DIR}/build"
OUT_JSON="${OUT_DIR}/main.json"

mkdir -p "${OUT_DIR}"

p4c-bm2-ss --arch v1model --std p4-16 -o "${OUT_JSON}" "${P4_SRC}"

echo "Generated ${OUT_JSON}"
