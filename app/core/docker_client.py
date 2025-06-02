import docker

client = docker.from_env()
CONTAINER_NAME = "vnc-webide"

# PTY 소켓도 여기에 저장
pty_socket = None