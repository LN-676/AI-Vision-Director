#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
API_BIN="${PROJECT_DIR}/.venv/bin/ai-vision-director-api"
DESKTOP_BIN="${PROJECT_DIR}/.venv/bin/ai-vision-director-qt"
DASHBOARD_BIN="${PROJECT_DIR}/dashboard/node_modules/.bin/vinext"
NODE_BIN="$(command -v node 2>/dev/null || true)"
if [[ -z "${NODE_BIN}" ]]; then
  CODEX_NODE_BIN="/Users/${USER}/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
  [[ -x "${CODEX_NODE_BIN}" ]] && NODE_BIN="${CODEX_NODE_BIN}"
fi

if [[ ! -x "${PYTHON_BIN}" || ! -x "${API_BIN}" || ! -x "${DESKTOP_BIN}" ]]; then
  print "Missing .venv installation. Follow README > Tablet Remote Control MVP."
  exit 1
fi
if [[ ! -x "${DASHBOARD_BIN}" ]]; then
  print "Missing dashboard dependencies. Run: cd dashboard && npm install"
  exit 1
fi
if [[ -z "${NODE_BIN}" || ! -x "${NODE_BIN}" ]]; then
  print "Node.js was not found. Install Node.js 22 or run: brew install node"
  exit 1
fi
export PATH="${NODE_BIN:h}:${PATH}"

LAN_IP="${AIVD_LAN_IP:-$(ipconfig getifaddr en0 2>/dev/null || true)}"
if [[ -z "${LAN_IP}" ]]; then
  LAN_IP="$(ipconfig getifaddr en1 2>/dev/null || true)"
fi
if [[ -z "${LAN_IP}" ]]; then
  print "Could not determine LAN IP. Set AIVD_LAN_IP before running."
  exit 1
fi

export AIVD_EDGE_NODE_ID="${AIVD_EDGE_NODE_ID:-edge-mac-01}"
export AIVD_EDGE_DEVICE_TOKEN="${AIVD_EDGE_DEVICE_TOKEN:-$(openssl rand -hex 24)}"
export AIVD_EDGE_PREVIEW_DIR="${AIVD_EDGE_PREVIEW_DIR:-${PROJECT_DIR}/outputs/edge-preview}"
export AIVD_CONTROL_API_URL="http://127.0.0.1:8080"
export AIVD_CORS_ALLOW_ORIGINS="http://${LAN_IP}:3000,http://127.0.0.1:3000"
export NEXT_PUBLIC_AIVD_API_BASE_URL="http://${LAN_IP}:8080"

API_PID=""
DASHBOARD_PID=""
cleanup() {
  [[ -n "${DASHBOARD_PID}" ]] && kill "${DASHBOARD_PID}" 2>/dev/null || true
  [[ -n "${API_PID}" ]] && kill "${API_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "${PROJECT_DIR}"
"${API_BIN}" --host 0.0.0.0 --port 8080 &
API_PID=$!

cd "${PROJECT_DIR}/dashboard"
"${DASHBOARD_BIN}" dev --hostname 0.0.0.0 --port 3000 &
DASHBOARD_PID=$!

print ""
print "AI Vision Director Remote Console:"
print "  http://${LAN_IP}:3000/remote"
print ""
print "Keep Mac, iPhone, and Tablet on the same private LAN."
print "Closing the Desktop stops this local MVP control plane."
print ""

cd "${PROJECT_DIR}"
"${DESKTOP_BIN}"
