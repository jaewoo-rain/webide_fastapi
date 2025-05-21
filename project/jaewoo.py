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
DOCKER_NAME = "docker-file"
DOCKER_DISPLAY = ":1"

# 기본 이미지 설정 파일, 다른 이미지 받으면 대체 됨
# "이렇게 생긴 JSON을 기대해주세요"
# { "image": "my-custom-image" } 이렇게 생긴것을 기대함함
# BaseModel = 쿼리 같은것이 아니라 명시적으로 body 형태로 오도록 함
class RunRequest(BaseModel):
    image: str = "docker-file"

def get_used_host_ports():
    """현재 Docker가 할당 중인 호스트 포트 목록을 반환합니다."""
    used = set() # 포트 번호를 중복 없이 담기 위해 
    for container in docker_client.containers.list(all=True): # 현재 실행 중인 컨테이너뿐 아니라, 정지(stopped) 상태인 컨테이너까지 전부 나열한 리스트
        ports = container.attrs.get('NetworkSettings', {}).get('Ports') or {} # 컨테이너의 포트 바인딩 정보 꺼내기, 
                                                                              # container.attrs["NetworkSettings"]["Ports"] 동일
        for bindings in ports.values():
            if bindings:
                for bind in bindings:
                    host_port = int(bind.get('HostPort'))
                    used.add(host_port)
                    """
                    ports = {
                                "10007/tcp": [
                                    {"HostIp": "0.0.0.0", "HostPort": "32768"}
                                ],
                                "6080/tcp": None
                            }
                    ports.keys() → dict_keys(["10007/tcp", "6080/tcp"])
                    ports.values() → dict_values([ [{"HostIp":...,"HostPort":"32768"}], None ])
                    """
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
    raise RuntimeError(f"{max_tries}회 시도 안에 빈 포트가 없습니다 ")

@app.post("/create")
def run_container(req: RunRequest):
    # global DOCKER_NAME
    # 사용 가능한 포트 쌍 탐색
    try:
        vnc_port, novnc_port = find_free_ports(
            DEFAULT_VNC_START, DEFAULT_NOVNC_START, MAX_TRIES
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    container_name = f"webide-vnc-{uuid.uuid4().hex[:8]}"
    # DOCKER_NAME = container_name
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





import ast

import ast

def is_turtle_code(source: str) -> bool:
    tree = ast.parse(source)

    has_import = False
    has_usage  = False

    for node in ast.walk(tree):
        # 1) import turtle 또는 import turtle as t
        if isinstance(node, ast.Import):
            if any(alias.name == "turtle" for alias in node.names):
                has_import = True

        # 2) from turtle import forward, Screen 등
        if isinstance(node, ast.ImportFrom) and node.module == "turtle":
            has_import = True

        # 3) turtle.xxx() 호출 (Attribute)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "turtle":
                has_usage = True

    # import와 usage가 모두 있어야 turtle 코드로 본다
    return has_import and has_usage


# def is_turtle_code(source: str) -> bool:
#     tree = ast.parse(source)
#     for node in ast.walk(tree):
#         # 1) import turtle 또는 import turtle as t
#         if isinstance(node, ast.Import):
#             if any(alias.name == "turtle" for alias in node.names):
#                 return True
#         # 2) from turtle import forward 등
#         if isinstance(node, ast.ImportFrom) and node.module == "turtle":
#             return True
#         # 3) 실제 turtle.<something>() 호출
#         if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
#             if node.value.id in ("turtle",):
#                 return True
#     return False


# 2. "/run"은 코드 실행 처리
@app.post("/run")
async def run_code(request: Request):
    body = await request.json()
    code = body.get("code")
    if not code:
        return JSONResponse(content={"error": "No code provided"}, status_code=400)

    filename = "temp_turtle.py"
    local_path = os.path.join(os.getcwd(), filename)

    utf8_header = "# -*- coding: utf-8 -*-\n"

    with open(local_path, "w") as f:
        f.write(utf8_header + code)

    remote_path = f"/tmp/{filename}"

    # 기존 프로세스 죽이기
    subprocess.run([
        "docker", "exec", DOCKER_NAME,
        "pkill", "-f", f"python3 {remote_path}"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 파일 복사
    subprocess.run([
        "docker", "cp", local_path, f"{DOCKER_NAME}:{remote_path}"
    ])


    # turtle 코드인지 확인

    try:
        if is_turtle_code(code):
            # GUI 실행하기
            subprocess.Popen([
                "docker", "exec", "-e", f"DISPLAY={DOCKER_DISPLAY}",
                DOCKER_NAME, "python3", remote_path
            ])
            return JSONResponse(
                status_code=200,
                content= {"status": "running", "type": "turtle"}
            )
        else:
            # CLI 실행하기
            result = subprocess.run([
                "docker", "exec",
                DOCKER_NAME, "python3", remote_path
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            output = result.stdout.decode() + result.stderr.decode()
            # return {"status": "done", "type": "text", "output": output}
            return JSONResponse(
                status_code=200,
                content= {"status": "done", "type": "text", "output": output}
            )
    except Exception as e:
        # 예외 메시지를 문자열로 변환
        # return {"status": "done", "type": "text", "output": str(e)}

        err_msg = str(e)
        # 필요시 traceback도 붙일 수 있습니다:
        import traceback; 
        err_msg = traceback.format_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "type": "text", "output": err_msg}
        )

