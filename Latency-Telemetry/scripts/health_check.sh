#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
P4_FILE="${ROOT_DIR}/p4/main.p4"
BUILD_DIR="${ROOT_DIR}/build"
OUT_JSON="${BUILD_DIR}/main.json"

require_cmd() {
    local cmd="$1"
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        echo "[ERROR] Missing command: ${cmd}"
        exit 1
    fi
    echo "[OK] Found ${cmd}: $(command -v "${cmd}")"
}

echo "== Command checks =="
require_cmd p4c-bm2-ss
require_cmd simple_switch
require_cmd simple_switch_CLI
require_cmd mn

echo
echo "== P4 compilation test =="
mkdir -p "${BUILD_DIR}"
p4c-bm2-ss --arch v1model --std p4-16 -o "${OUT_JSON}" "${P4_FILE}"
if [[ ! -s "${OUT_JSON}" ]]; then
    echo "[ERROR] Compilation output not generated: ${OUT_JSON}"
    exit 1
fi
echo "[OK] main.p4 compiled to ${OUT_JSON}"

echo
echo "== Python import sanity =="
python3 - <<'PY'
import importlib
mods = ["mininet", "scapy"]
for m in mods:
    importlib.import_module(m)
print("[OK] Python modules import successfully")
PY

echo
echo "== Mininet smoke test =="
if [[ "${EUID}" -ne 0 ]]; then
    if ! sudo -n true >/dev/null 2>&1; then
        echo "[ERROR] Root is required for Mininet tests. Run with sudo or enable passwordless sudo."
        exit 1
    fi
fi

sudo mn -c >/dev/null 2>&1 || true
if ! sudo python3 - <<'PY'
from mininet.link import TCLink
from mininet.net import Mininet

net = Mininet(controller=None, link=TCLink)
h1 = net.addHost("h1", ip="10.99.0.1/24")
h2 = net.addHost("h2", ip="10.99.0.2/24")
net.addLink(h1, h2)

net.start()
loss = net.ping([h1, h2], timeout=1)
net.stop()

if loss != 0.0:
    raise SystemExit(f"Mininet smoke ping failed: loss={loss}%")

print("[OK] Mininet direct-link ping passed (0% dropped).")
PY
then
    echo "[ERROR] Mininet smoke test failed."
    exit 1
fi

echo
echo "Health check complete: environment is ready."
