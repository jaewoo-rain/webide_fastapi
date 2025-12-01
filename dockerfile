
# 1. 베이스 이미지
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    VNC_PASSWORD=jaewoo \
    DISPLAY=:1 \
    VNC_GEOMETRY=1024x768 \
    VNC_DEPTH=24 \
    VNC_PORT=5901 \
    NOVNC_PORT=6081 \
    USER=root

RUN printf 'Acquire::https::Verify-Peer "false";\nAcquire::https::Verify-Host "false";\n' \
     > /etc/apt/apt.conf.d/99bootstrap-ca && \
    apt-get update && apt-get install -y ca-certificates && \
    rm /etc/apt/apt.conf.d/99bootstrap-ca

RUN apt-get update && apt-get install -y --no-install-recommends \
    tigervnc-standalone-server tigervnc-tools  \
    x11-xserver-utils \
    x11-utils \
    nano vim curl git \
    python3 python3-pip python3-venv python3-tk python3-wxgtk4.0 \
    dos2unix && \
    rm -rf /var/lib/apt/lists/*

# 3. noVNC & websockify 설치
WORKDIR /opt
RUN git clone https://github.com/novnc/noVNC.git && \
    cd noVNC && git checkout v1.2.0 && \
    git clone https://github.com/novnc/websockify && \
    cd websockify && pip3 install . --break-system-packages

# 4. VNC 설정
RUN mkdir -p /root/.vnc && \
    printf "%s\n%s\nn\n" "$VNC_PASSWORD" "$VNC_PASSWORD" | vncpasswd

# 5. xstartup 설정
# RUN echo '#!/bin/bash\nxsetroot -solid grey\nwhile true; do sleep 1000; done\n' > /root/.vnc/xstartup && chmod +x /root/.vnc/xstartup
RUN printf '%s\n' \
    "#!/bin/bash" \
    "xsetroot -solid grey" \
    "xsetroot -cursor_name left_ptr" \
    "while true; do sleep 1000; done" \
    > /root/.vnc/xstartup && \
    chmod +x /root/.vnc/xstartup

# 6. 실행 스크립트 복사
COPY start.sh /opt/start.sh
RUN dos2unix /opt/start.sh && chmod +x /opt/start.sh

# 7. 포트 열기 (VNC, noVNC, CLI용 WebSocket용도 8001)
EXPOSE ${VNC_PORT} ${NOVNC_PORT}

# 8. 컨테이너 시작 시 스크립트 실행
CMD ["bash", "/opt/start.sh"]