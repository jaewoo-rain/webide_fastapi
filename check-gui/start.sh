#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}▶ Starting VNC Server on ${DISPLAY} ...${NC}"
vncserver ${DISPLAY} \
  -rfbport ${VNC_PORT} \
  -localhost no \
  -geometry ${VNC_GEOMETRY} \
  -depth ${VNC_DEPTH}

echo -e "${GREEN}▶ Starting noVNC WebSocket Proxy on :${NOVNC_PORT} ...${NC}"
websockify --web=/opt/noVNC ${NOVNC_PORT} localhost:${VNC_PORT} &

# 컨테이너가 죽지 않게 유지
echo -e "${YELLOW}⏳ Container idle and ready. Use FastAPI to trigger code.${NC}"
tail -f /dev/null

# docker build -t webide-vnc .
# docker run -d --name vnc-webide -p 6081:6081 -e VNC_PORT=5901 -e NOVNC_PORT=6081 -e VNC_GEOMETRY=1024x1024 -e VNC_DEPTH=24 webide-vnc
