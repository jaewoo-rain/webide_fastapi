

#!/bin/bash
set -e

VENV_PATH="/tmp/user_venv"

# 1. 가상환경 없으면 생성
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    echo "[INFO] Python 가상환경 생성 중... ($VENV_PATH)"
    python3 -m venv "$VENV_PATH"
    echo "[INFO] 가상환경 생성 완료!"
else
    echo "[INFO] 이미 가상환경이 존재합니다."
fi

vncserver ${DISPLAY} \
  -rfbport ${VNC_PORT} \
  -localhost no \
  -geometry ${VNC_GEOMETRY} \
  -depth ${VNC_DEPTH}

websockify --web=/opt/noVNC ${NOVNC_PORT} localhost:${VNC_PORT} &

# 컨테이너가 죽지 않게 유지
tail -f /dev/null
