#!/bin/bash
set -e

# 1) VNC 서버 기동
vncserver :1 \
  -rfbport ${VNC_PORT} \
  -localhost no \
  -geometry ${VNC_GEOMETRY} \
  -depth ${VNC_DEPTH}

# 2) websockify를 PID 1로 실행(쉘 교체)
#    --web 는 noVNC HTML/JS 파일이 있는 폴더를 가리킵니다.
exec websockify \
  --web=/noVNC \
  ${NOVNC_PORT} localhost:${VNC_PORT}
