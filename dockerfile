# docker build -t docker-file .

# 1. 베이스 이미지
FROM ubuntu:24.04

# 2. 비대화형 apt 동작을 위해 환경 변수 설정
ENV DEBIAN_FRONTEND=noninteractive \
    VNC_PASSWORD=jaewoo \
    VNC_GEOMETRY=1024x768 \
    VNC_DEPTH=24 \
    VNC_PORT=10007 \
    NOVNC_PORT=6080

# 3. 필수 패키지 설치
RUN apt-get update && \
      apt-get install -y --no-install-recommends \
      tigervnc-standalone-server \
      tightvncserver  \
      nano vim \
      git npm python3-pip x11-xserver-utils python3-tk && \
    rm -rf /var/lib/apt/lists/*

# 4. VNC 비밀번호 자동 설정
RUN mkdir -p /root/.vnc && \
    printf "%s\n%s\nn\n" "$VNC_PASSWORD" "$VNC_PASSWORD" | vncpasswd

# 5. xstartup 스크립트 구성 (배경색만 설정하고 무한 루프)
# VNC xstartup 스크립트 생성

# VNC xstartup 스크립트 생성 + 실행 권한 부여
RUN printf '#!/bin/bash\nxsetroot -solid grey\nwhile true; do sleep 1000; done\n' \
    > /root/.vnc/xstartup && chmod +x /root/.vnc/xstartup

# 6. noVNC & websockify 설치
# opt 디렉터리 만들어서 진행하기기
# WORKDIR /opt  
RUN git clone https://github.com/novnc/noVNC.git && \
    cd noVNC && \
    npm install && \
    git clone https://github.com/novnc/websockify.git && \
    cd websockify && \
    pip3 install . --break-system-packages

# 7. 시작 스크립트 추가
COPY start.sh /noVNC/start.sh
RUN chmod +x /noVNC/start.sh

# 8. 포트 오픈
EXPOSE ${VNC_PORT} ${NOVNC_PORT}

# 9. 컨테이너 시작 시 스크립트 실행
CMD ["/opt/start.sh"]


# # 1. 베이스 이미지
# FROM ubuntu:24.04

# # 2. 비대화형 apt 동작을 위해 환경 변수 설정
# ENV DEBIAN_FRONTEND=noninteractive \
#     VNC_PASSWORD=jaewoo \
#     VNC_GEOMETRY=1024x768 \
#     VNC_DEPTH=24 \
#     VNC_PORT=10007 \
#     NOVNC_PORT=6080

# # 3. 필수 패키지 및 dos2unix 설치
# RUN apt-get update && \
#     apt-get install -y --no-install-recommends \
#       tigervnc-standalone-server \
#       tightvncserver \
#       nano vim \
#       git npm python3-pip x11-xserver-utils python3-tk \
#       dos2unix && \
#     rm -rf /var/lib/apt/lists/*

# # 4. start.sh 복사 후 개행 변환 및 실행권한 부여
# COPY start.sh /opt/start.sh
# RUN dos2unix /opt/start.sh && chmod +x /opt/start.sh

# # 5. VNC 비밀번호 자동 설정
# RUN mkdir -p /root/.vnc && \
#     printf "%s\n%s\nn\n" "$VNC_PASSWORD" "$VNC_PASSWORD" | vncpasswd

# # 6. xstartup 스크립트 구성 (배경색만 설정하고 무한 루프)
# RUN printf '#!/bin/bash\nxsetroot -solid grey\nwhile true; do sleep 1000; done\n' \
#     > /root/.vnc/xstartup && chmod +x /root/.vnc/xstartup

# # 7. noVNC & websockify 설치
# WORKDIR /opt
# RUN git clone https://github.com/novnc/noVNC.git && \
#     cd noVNC && npm install && \
#     git clone https://github.com/novnc/websockify.git && \
#     cd websockify && pip3 install . --break-system-packages

# # 8. 포트 오픈
# EXPOSE ${VNC_PORT} ${NOVNC_PORT}

# # 9. 컨테이너 시작 시 스크립트 실행
# #    bash로 호출하면 shebang 깨짐 문제도 우회됩니다.
# CMD ["bash", "/opt/start.sh"]