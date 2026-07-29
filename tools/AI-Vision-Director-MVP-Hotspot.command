#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
WIFI_INTERFACE="${AIVD_WIFI_INTERFACE:-en0}"
WIFI_IP="$(ipconfig getifaddr "${WIFI_INTERFACE}" 2>/dev/null || true)"

if [[ -z "${WIFI_IP}" ]]; then
  print "Wi-Fi or phone hotspot was not found on ${WIFI_INTERFACE}."
  print "Connect the Mac to the same hotspot as the iPad, then try again."
  exit 1
fi

LOCAL_HOST_NAME="$(scutil --get LocalHostName 2>/dev/null || true)"
if [[ -z "${LOCAL_HOST_NAME}" ]]; then
  print "Could not determine the Mac Bonjour name."
  exit 1
fi

export AIVD_LAN_IP="${WIFI_IP}"
export AIVD_LAN_HOST="${LOCAL_HOST_NAME}.local"
REMOTE_URL="http://${AIVD_LAN_HOST}:3000/remote"
IP_FALLBACK_URL="http://${AIVD_LAN_IP}:3000/remote"

if command -v pbcopy >/dev/null 2>&1; then
  print -rn "${REMOTE_URL}" | pbcopy
fi

print ""
print "Wi-Fi / phone hotspot detected:"
print "  Mac: ${AIVD_LAN_IP} (${AIVD_LAN_HOST}, ${WIFI_INTERFACE})"
print "  Tablet Remote: ${REMOTE_URL}"
print "  IP fallback: ${IP_FALLBACK_URL}"
print "  The stable Tablet Remote URL was copied to the Apple clipboard."
print ""

exec "${SCRIPT_DIR}/AI-Vision-Director-MVP.command"
