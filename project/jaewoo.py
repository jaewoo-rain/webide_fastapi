from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import uuid
import docker
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import subprocess
import os

app = FastAPI()

# Static 폴더 등록
app.mount("/static", StaticFiles(directory="static"), name="static")

docker_client = docker.from_env()

# 기본 포트 설정
DEFAULT_VNC_START = 10007
DEFAULT_NOVNC_START = 6080
MAX_TRIES = 10
global DOCKER_NAME
DOCKER_DISPLAY = ":1"

# 기본 이미지 설정 파일, 다른 이미지 받으면 대체 됨
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

@app.post("/create")g
def run_container(req: RunRequest):
    global DOCKER_NAME    
    # 사용 가능한 포트 쌍 탐색
    try:
        vnc_port, novnc_port = find_free_ports(
            DEFAULT_VNC_START, DEFAULT_NOVNC_START, MAX_TRIES
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    container_name = f"webide-vnc-{uuid.uuid4().hex[:8]}"
    DOCKER_NAME = container_name
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



# 1. "/" 접속하면 static 폴더에 있는 index.html 읽어서 보내기
@app.get("/", response_class=HTMLResponse)
async def get_index():
    with open("static/home.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/main", response_class=HTMLResponse)
def go_main():
    return "index.h"
# 2. "/run"은 코드 실행 처리
@app.post("/run")
async def run_code(request: Request):
    body = await request.json()
    code = body.get("code")
    if not code:
        return JSONResponse(content={"error": "No code provided"}, status_code=400)

    filename = "temp_turtle.py"
    local_path = os.path.join(os.getcwd(), filename)
    with open(local_path, "w") as f:
        f.write(code)

    remote_path = f"/tmp/{filename}"

    # turtle 코드인지 확인
    is_turtle = "import turtle" in code

    # 기존 프로세스 죽이기
    subprocess.run([
        "docker", "exec", DOCKER_NAME,
        "pkill", "-f", f"python3 {remote_path}"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 파일 복사
    subprocess.run([
        "docker", "cp", local_path, f"{DOCKER_NAME}:{remote_path}"
    ])

    if is_turtle:
        subprocess.Popen([
            "docker", "exec", "-e", f"DISPLAY={DOCKER_DISPLAY}",
            DOCKER_NAME, "python3", remote_path
        ])
        return {"status": "running", "type": "turtle"}
    else:
        result = subprocess.run([
            "docker", "exec", "-e", f"DISPLAY={DOCKER_DISPLAY}",
            DOCKER_NAME, "python3", remote_path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        output = result.stdout.decode() + result.stderr.decode()
        return {"status": "done", "type": "text", "output": output}


