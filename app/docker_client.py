import docker

_docker = None

def get_docker():
    global _docker
    if _docker is None:
        _docker = docker.from_env()
    return _docker
