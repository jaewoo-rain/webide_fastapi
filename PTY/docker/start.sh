#!/bin/bash
set -e

# 1. VNC 서버 실행
vncserver :1 -geometry ${VNC_GEOMETRY} -depth ${VNC_DEPTH} -rfbport ${VNC_PORT} -localhost no

# 2. noVNC 실행
/noVNC/utils/novnc_proxy --vnc localhost:${VNC_PORT} --listen ${NOVNC_PORT} &

# 3. FastAPI 서버 실행
uvicorn main:app --host 0.0.0.0 --port 8000
