from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uuid
import docker
import subprocess
import os
from datetime import datetime
import ast
import traceback

app = FastAPI()
docker_client = docker.from_env()

# Static 폴더 등록
app.mount("/static", StaticFiles(directory="static"), name="static")

# 사전 정의된 컨테이너 목록 및 상태 (MVP용 인메모리)
PREDEFINED_CONTAINERS = {
    "python": [
        {"id": "python-1", "port": 30001},
        {"id": "python-2", "port": 30002},
        {"id": "python-3", "port": 30003}
    ],
    "nodejs": [
        {"id": "node-1", "port": 31001},
        {"id": "node-2", "port": 31002}
    ]
}

container_status = {
    "python-1": {"status": "available", "user_id": None, "last_heartbeat": None},
    "python-2": {"status": "available", "user_id": None, "last_heartbeat": None},
    "python-3": {"status": "available", "user_id": None, "last_heartbeat": None},
    "node-1": {"status": "available", "user_id": None, "last_heartbeat": None},
    "node-2": {"status": "available", "user_id": None, "last_heartbeat": None},
}

# 기본 포트 설정 및 최대 시도 횟수
DEFAULT_VNC_START = 10007
DEFAULT_NOVNC_START = 6080
MAX_TRIES = 10
DOCKER_DISPLAY = ":1"

# 요청 바디 모델: 이미지 이름
class RunRequest(BaseModel):
    image: str = "docker-file"


def get_used_host_ports() -> set[int]:
    """
    현재 Docker가 사용 중인 호스트 포트 번호 집합을 반환합니다.
    """
    used = set()
    for container in docker_client.containers.list(all=True):
        ports = container.attrs.get('NetworkSettings', {}).get('Ports') or {}
        for bindings in ports.values():
            if bindings:
                for bind in bindings:
                    used.add(int(bind.get('HostPort')))
    return used


def find_free_ports(vnc_start: int, novnc_start: int, max_tries: int) -> tuple[int, int]:
    """
    Docker에서 사용 중인 포트를 피해 사용 가능한 (vnc_port, novnc_port) 쌍을 찾아 반환합니다.
    """
    used = get_used_host_ports()
    for offset in range(max_tries):
        vport = vnc_start + offset
        nport = novnc_start + offset
        if vport not in used and nport not in used:
            return vport, nport
    raise RuntimeError(f"{max_tries}회 시도 내에 빈 포트가 없습니다.")


@app.post("/create")
def run_container(req: RunRequest):
    """
    사용자가 요청한 이미지로 새 컨테이너 생성 후 관련 정보 반환
    """
    try:
        vnc_port, novnc_port = find_free_ports(DEFAULT_VNC_START, DEFAULT_NOVNC_START, MAX_TRIES)
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
                f"{DEFAULT_NOVNC_START}/tcp": novnc_port,
            },
            restart_policy={"Name": "unless-stopped"},
        )
        return {
            "message": "Container started",
            "container_id": container.id,
            "name": container_name,
            "vnc_port": vnc_port,
            "novnc_port": novnc_port,
            "image": req.image,
        }
    except docker.errors.APIError as e:
        raise HTTPException(status_code=500, detail=f"Docker API error: {e.explanation}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/assign")
async def assign_container(req: RunRequest):
    """
    사전 정의된 컨테이너 중 사용 가능한 컨테이너를 사용자에게 할당
    """
    user_id = str(uuid.uuid4())  # 실제 서비스에선 인증된 사용자 ID로 대체 필요

    for container in PREDEFINED_CONTAINERS.get(req.image, []):
        cid = container["id"]
        status = container_status.get(cid)
        if status and status["status"] == "available":
            container_status[cid] = {
                "status": "busy",
                "user_id": user_id,
                "last_heartbeat": datetime.utcnow(),
            }
            return {
                "assigned": True,
                "container_id": cid,
                "user_id": user_id,
                "port": container["port"],
            }

    raise HTTPException(status_code=429, detail="No available container")


@app.get("/status/{name}")
def get_status(name: str):
    """
    컨테이너 이름으로 상태 조회
    """
    try:
        container = docker_client.containers.get(name)
        return {"name": name, "status": container.status}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", response_class=HTMLResponse)
async def get_index():
    """
    루트 경로 접속 시 static/home.html 반환
    """
    with open("static/home.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/main", response_class=HTMLResponse)
def go_main():
    return "index.h"

def is_turtle_code(source: str) -> bool:
    """
    주어진 파이썬 코드가 turtle 모듈을 사용하는지 검사
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "turtle" for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module == "turtle":
            return True
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "turtle":
                return True
    return False


@app.post("/run")
async def run_code(request: Request):
    """
    클라이언트로부터 받은 코드와 컨테이너 정보로 해당 컨테이너 내에서 코드 실행 처리
    """
    body = await request.json()
    code = body.get("code")
    container_name = body.get("container_name")
    image = body.get("image")

    if not code or not container_name:
        return JSONResponse(content={"error": "Code or container name missing"}, status_code=400)

    if image == "js-image":
        filename = "temp.js"
        local_path = os.path.join(os.getcwd(), filename)
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(code)
        remote_path = f"/tmp/{filename}"
    else:
        filename = "temp_turtle.py"
        local_path = os.path.join(os.getcwd(), filename)
        utf8_header = "# -*- coding: utf-8 -*-\n"
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(utf8_header + code)
        remote_path = f"/tmp/{filename}"

    # 기존 프로세스 종료
    subprocess.run(
        ["docker", "exec", container_name, "pkill", "-f", f"python3 {remote_path}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 파일 복사
    subprocess.run(["docker", "cp", local_path, f"{container_name}:{remote_path}"])

    try:
        if image == "js-image":
            # Node.js 코드 실행
            result = subprocess.run(
                ["docker", "exec", container_name, "node", remote_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            output = result.stdout.decode() + result.stderr.decode()
            return JSONResponse({"status": "done", "type": "text", "output": output})

        else:
            # 파이썬 코드 실행
            if is_turtle_code(code):
                # GUI용 turtle 코드 실행 (백그라운드)
                subprocess.Popen(
                    [
                        "docker",
                        "exec",
                        "-e",
                        f"DISPLAY={DOCKER_DISPLAY}",
                        container_name,
                        "python3",
                        remote_path,
                    ]
                )
                return JSONResponse({"status": "running", "type": "gui"})
            else:
                # CLI 실행
                result = subprocess.run(
                    ["docker", "exec", container_name, "python3", remote_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                output = result.stdout.decode() + result.stderr.decode()
                return JSONResponse({"status": "done", "type": "text", "output": output})

    except Exception:
        err_msg = traceback.format_exc()
        return JSONResponse(status_code=500, content={"status": "error", "type": "text", "output": err_msg})
