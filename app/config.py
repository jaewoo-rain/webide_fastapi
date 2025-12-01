from typing import Final
import os

# security
ALGORITHM = "HS256"
JWT_SECRET = "TlvldbghkdlxlddlqslekdkwkdkwkghkdlxlddufmasjanejdnjdpdjzjsdmfxmfdjvldbvldbTlvldbvldbvldbTlvldb"

# roles
ROLE_FREE: Final = "ROLE_FREE"
ROLE_MEMBER: Final = "ROLE_MEMBER"
ROLE_ADMIN: Final = "ROLE_ADMIN"


FREE_MAX_CONTAINERS = int(os.getenv("FREE_MAX_CONTAINERS", "3"))
DOCKER_NETWORK = os.getenv("DOCKER_NETWORK", None)  # 필요하면 bridge 이름
# SPRING_BOOT_API_URL="http://localhost:8080/internal/api/"


VNC_IMAGE = "vnc-webide"
CONTAINER_ENV_DEFAULT= {
    "VNC_PORT": "5901",
    "NOVNC_PORT": "6081",
    "VNC_GEOMETRY": "1024x768",
    "VNC_DEPTH": "24",
}
INTERNAL_NOVNC_PORT = 6081 # 내부 noVNC 포트 번호
ALLOWED_NOVNC_PORTS = list(range(10000, 10101))


WORKSPACE="/opt/workspace" # 코드 저장 폴더
SPRING_BOOT_API_URL="http://ide-boot:8080"

