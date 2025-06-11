# #!/bin/bash
# set -e

# # VNC 서버 실행
# vncserver :1 -geometry ${VNC_GEOMETRY} -depth ${VNC_DEPTH}

# # noVNC 실행
# /opt/noVNC/utils/launch.sh --vnc localhost:5901 --listen 6080

# # 컨테이너는 여기서 대기 (무한 sleep)
# tail -f /dev/null

#!/bin/bash
set -e

vncserver ${DISPLAY} \
  -rfbport ${VNC_PORT} \
  -localhost no \
  -geometry ${VNC_GEOMETRY} \
  -depth ${VNC_DEPTH}

websockify --web=/opt/noVNC ${NOVNC_PORT} localhost:${VNC_PORT} &

# 컨테이너가 죽지 않게 유지
tail -f /dev/null

# docker build -t webide-vnc .
# docker run -d --name vnc-webide -p 6081:6081 -e VNC_PORT=5901 -e NOVNC_PORT=6081 -e VNC_GEOMETRY=1024x1024 -e VNC_DEPTH=24 webide-vnc
