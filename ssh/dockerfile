FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y openssh-server \
 && mkdir /var/run/sshd

# 1) 루트 로그인 비활성화
RUN sed -i 's/#PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config

# 2) 사용자 계정 생성 & 비밀번호 설정
RUN useradd -m jaewoo && echo 'jaewoo:jaewoo'  | chpasswd \
 && useradd -m test1 && echo 'test1:test1'  | chpasswd \
 && useradd -m test2 && echo 'test2:test2'  | chpasswd

# 3) 패스워드 인증 허용 (필요시)
RUN sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config

EXPOSE 22
CMD ["/usr/sbin/sshd","-D"]
