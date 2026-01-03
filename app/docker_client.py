# docker_client.py
import os
import docker

_docker = None

def get_docker():
    # 🔹 K8s 환경에서는 Docker 클라이언트 안 씀
    if os.getenv("K8S_MODE", "false").lower() == "true":
        return None

    global _docker
    if _docker is None:
        _docker = docker.from_env()
    return _docker
