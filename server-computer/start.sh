#!/bin/bash
set -e

# VNC 서버 실행
vncserver :1 -geometry ${VNC_GEOMETRY} -depth ${VNC_DEPTH}

# noVNC 실행
/opt/noVNC/utils/launch.sh --vnc localhost:5901 --listen 6080

# 컨테이너는 여기서 대기 (무한 sleep)
tail -f /dev/null