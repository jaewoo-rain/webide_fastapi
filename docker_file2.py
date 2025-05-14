from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uuid
import docker

app = FastAPI()
docker_client = docker.from_env()

# 기본 포트 설정
DEFAULT_VNC_START = 10007
DEFAULT_NOVNC_START = 6080
MAX_TRIES = 10

class RunRequest(BaseModel):
    image: str = "docker-file"


def get_used_host_ports():
    """현재 Docker가 할당 중인 호스트 포트 목록을 반환합니다."""
    used = set()
    for container in docker_client.containers.list(all=True):
        ports = container.attrs.get('NetworkSettings', {}).get('Ports') or {}
        for bindings in ports.values():
            if bindings:
                for bind in bindings:
                    host_port = int(bind.get('HostPort'))
                    used.add(host_port)
    return used


def find_free_ports(vnc_start: int, novnc_start: int, max_tries: int):
    """
    Docker의 사용 중인 포트를 피해서
    사용 가능한 vnc/novnc 포트 쌍을 찾아 리턴합니다.
    """
    used = get_used_host_ports()
    for offset in range(max_tries):
        vport = vnc_start + offset
        nport = novnc_start + offset
        if vport not in used and nport not in used:
            return vport, nport
    raise RuntimeError(f"No free ports available after {max_tries} tries.")

@app.post("/create")
def run_container(req: RunRequest):
    # 사용 가능한 포트 쌍 탐색
    try:
        vnc_port, novnc_port = find_free_ports(
            DEFAULT_VNC_START, DEFAULT_NOVNC_START, MAX_TRIES
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    container_name = f"webide-vnc-{uuid.uuid4().hex[:8]}"
    try:
        container = docker_client.containers.run(
            req.image,
            detach=True,
            name=container_name,
            ports={
                f"{DEFAULT_VNC_START}/tcp": vnc_port,
                f"{DEFAULT_NOVNC_START}/tcp": novnc_port
            },
            restart_policy={"Name": "unless-stopped"}
        )
        return {
            "message": "Container started",
            "container_id": container.id,
            "name": container_name,
            "vnc_port": vnc_port,
            "novnc_port": novnc_port
        }
    except docker.errors.APIError as e:
        raise HTTPException(status_code=500, detail=f"Docker API error: {e.explanation}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status/{name}")
def get_status(name: str):
    try:
        container = docker_client.containers.get(name)
        return {"name": name, "status": container.status}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 실행 예시:
# uvicorn main:app --reload --host 0.0.0.0 --port 5000