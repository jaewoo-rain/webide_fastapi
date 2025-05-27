#!/bin/bash
set -e

# 0) 로그 색상용 함수
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1) VNC 서버 기동
echo -e "${GREEN}▶ Starting VNC Server on :1 ...${NC}"
vncserver :1 \
  -rfbport ${VNC_PORT} \
  -localhost no \
  -geometry ${VNC_GEOMETRY} \
  -depth ${VNC_DEPTH}

# 2) noVNC 웹소켓 포워딩 시작
echo -e "${GREEN}▶ Starting noVNC Websocket Proxy on :${NOVNC_PORT} ...${NC}"
websockify --web=/noVNC ${NOVNC_PORT} localhost:${VNC_PORT} &
WEBSOCKIFY_PID=$!

# 3) GUI 디스플레이 감시 함수
function wait_for_gui() {
    echo -e "${YELLOW}⏳ Waiting for GUI application to appear on DISPLAY=:1 ...${NC}"
    export DISPLAY=:1
    for i in {1..30}; do
        # xwininfo는 X 디스플레이에 창이 하나라도 있는지 확인
        if xwininfo -root -tree | grep -q '(".*")'; then
            echo -e "${GREEN}✅ GUI Detected! Open your browser at: http://localhost:${NOVNC_PORT} ${NC}"
            return
        fi
        sleep 1
    done
    echo -e "${YELLOW}⚠️  No GUI application detected within 30 seconds.${NC}"
}

wait_for_gui

# 4) 포그라운드 유지 (websockify는 백그라운드로 돌고 있음)
wait $WEBSOCKIFY_PID
