#!/usr/bin/env bash
set -euo pipefail

# Full environment bootstrap for Ubuntu + BMv2 + p4c + Mininet.
# This script builds p4c and BMv2 from source for reproducibility.

P4_INSTALL_DIR="${P4_INSTALL_DIR:-/opt/p4}"
JOBS="${JOBS:-$(nproc)}"

if [[ "${EUID}" -eq 0 ]]; then
    SUDO=""
else
    SUDO="sudo"
fi

echo "[1/6] Installing Ubuntu packages..."
${SUDO} apt-get update
${SUDO} DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential \
    cmake \
    automake \
    autoconf \
    libtool \
    pkg-config \
    git \
    wget \
    curl \
    ca-certificates \
    bison \
    flex \
    libfl-dev \
    libgc-dev \
    libboost-dev \
    libboost-system-dev \
    libboost-thread-dev \
    libboost-program-options-dev \
    libboost-filesystem-dev \
    libevent-dev \
    libreadline-dev \
    libssl-dev \
    libffi-dev \
    libgmp-dev \
    libpcap-dev \
    libnanomsg-dev \
    libgrpc++-dev \
    protobuf-compiler \
    libprotobuf-dev \
    libprotobuf-c-dev \
    python3 \
    python3-pip \
    python3-dev \
    python3-setuptools \
    python3-wheel \
    python3-thrift \
    thrift-compiler \
    mininet

echo "[2/6] Installing Python helper packages..."
python3 -m pip install --upgrade pip
python3 -m pip install --upgrade scapy ipaddress psutil

echo "[3/6] Preparing source tree in ${P4_INSTALL_DIR}..."
${SUDO} mkdir -p "${P4_INSTALL_DIR}"
${SUDO} chown -R "${USER}:${USER}" "${P4_INSTALL_DIR}"
cd "${P4_INSTALL_DIR}"

echo "[4/6] Building PI (P4Runtime support layer)..."
if [[ ! -d PI ]]; then
    git clone --depth 1 https://github.com/p4lang/PI.git
fi
cd PI
git submodule update --init --recursive
./autogen.sh
./configure --with-proto
make -j"${JOBS}"
${SUDO} make install
${SUDO} ldconfig
cd "${P4_INSTALL_DIR}"

echo "[5/6] Building BMv2 simple_switch..."
if [[ ! -d behavioral-model ]]; then
    git clone --depth 1 https://github.com/p4lang/behavioral-model.git
fi
cd behavioral-model
git submodule update --init --recursive
./autogen.sh
./configure --with-pi
make -j"${JOBS}"
${SUDO} make install
${SUDO} ldconfig
cd "${P4_INSTALL_DIR}"

echo "[6/6] Building p4c compiler (p4c-bm2-ss)..."
if [[ ! -d p4c ]]; then
    git clone --depth 1 https://github.com/p4lang/p4c.git
fi
cd p4c
git submodule update --init --recursive
mkdir -p build
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j"${JOBS}"
${SUDO} make install
${SUDO} ldconfig

echo
for cmd in p4c-bm2-ss simple_switch simple_switch_CLI mn; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        echo "[ERROR] Command not found after install: ${cmd}"
        exit 1
    fi
    echo "[OK] ${cmd}: $(command -v "${cmd}")"
done

echo
echo "Environment ready. Next step: run scripts/health_check.sh"
