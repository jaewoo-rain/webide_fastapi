#!/bin/bash
set -e

# 색상
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # 리셋

# VNC 서버 시작
echo -e "${GREEN}▶ Starting VNC Server on :1 ...${NC}"
vncserver :1 \
  -rfbport ${VNC_PORT} \
  -localhost no \
  -geometry ${VNC_GEOMETRY} \
  -depth ${VNC_DEPTH}

# noVNC 웹소켓 프록시 실행
echo -e "${GREEN}▶ Starting noVNC WebSocket Proxy on :${NOVNC_PORT} ...${NC}"
websockify --web=/opt/noVNC ${NOVNC_PORT} localhost:${VNC_PORT} &
WEBSOCKIFY_PID=$!

# GUI 감지 루프 (항상 감시)
export DISPLAY=:1
echo -e "${YELLOW}⏳ Watching for GUI applications on DISPLAY=:1 ...${NC}"

while true; do
    if xwininfo -root -tree | grep -q '("'; then
        echo -e "${GREEN}✅ GUI Detected! Open your browser at: http://localhost:${NOVNC_PORT}${NC}"
    fi
    sleep 2
done &

# 포그라운드 유지
wait $WEBSOCKIFY_PID
