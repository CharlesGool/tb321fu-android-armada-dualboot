#!/bin/bash
# Build a static aarch64 qbootctl (linux-msm/qbootctl) in a rootless Alpine container.
# 在 rootless Alpine 容器里编译静态 aarch64 版 qbootctl。不需要 sudo。
set -euo pipefail
OUT="$(cd "$(dirname "$0")" && pwd)"
REV="${QBOOTCTL_REV:-39a6e6daaf029fb0a083777679a15ea2c18f72de}"
podman run --rm -v "$OUT:/out:Z" docker.io/library/alpine:3.22 sh -ec "
apk add -q build-base meson ninja git zlib-dev zlib-static linux-headers
git clone -q https://github.com/linux-msm/qbootctl /src
cd /src && git checkout -q $REV
LDFLAGS=-static meson setup build -Ddefault_library=static --prefer-static >/dev/null
ninja -C build >/dev/null
cp build/qbootctl /out/qbootctl"
podman rmi -i docker.io/library/alpine:3.22 >/dev/null
file "$OUT/qbootctl"
