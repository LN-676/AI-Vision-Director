#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
WIRED_INTERFACE="${AIVD_WIRED_INTERFACE:-en8}"
WIRED_IP="$(ipconfig getifaddr "${WIRED_INTERFACE}" 2>/dev/null || true)"

if [[ -z "${WIRED_IP}" ]]; then
  WIRED_IP="$(
    ifconfig "${WIRED_INTERFACE}" 2>/dev/null |
      awk '/inet 169[.]254[.]/{print $2; exit}'
  )"
fi

if [[ -z "${WIRED_IP}" ]]; then
  for CANDIDATE_INTERFACE in ${(z)"$(ifconfig -l)"}; do
    CANDIDATE_IP="$(
      ifconfig "${CANDIDATE_INTERFACE}" 2>/dev/null |
        awk '/inet 169[.]254[.]/{print $2; exit}'
    )"
    CANDIDATE_STATUS="$(
      ifconfig "${CANDIDATE_INTERFACE}" 2>/dev/null |
        awk '/status:/{print $2; exit}'
    )"
    if [[ -n "${CANDIDATE_IP}" && "${CANDIDATE_STATUS}" == "active" ]]; then
      WIRED_INTERFACE="${CANDIDATE_INTERFACE}"
      WIRED_IP="${CANDIDATE_IP}"
      break
    fi
  done
fi

if [[ -z "${WIRED_IP}" ]]; then
  print "Wired iPad network was not found."
  print "Reconnect the USB cable, unlock the iPad, and run this launcher again."
  exit 1
fi

LOCAL_HOST_NAME="$(scutil --get LocalHostName 2>/dev/null || true)"
if [[ -z "${LOCAL_HOST_NAME}" ]]; then
  print "Could not determine the Mac Bonjour name."
  exit 1
fi

export AIVD_LAN_IP="${WIRED_IP}"
export AIVD_LAN_HOST="${LOCAL_HOST_NAME}.local"

print ""
print "Wired iPad network detected:"
print "  Mac: ${AIVD_LAN_IP} (${AIVD_LAN_HOST}, ${WIRED_INTERFACE})"
print "  Remote: http://${AIVD_LAN_HOST}:3000/remote"
print ""

exec "${SCRIPT_DIR}/AI-Vision-Director-MVP.command"
