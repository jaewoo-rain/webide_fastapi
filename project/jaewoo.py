from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import uuid
import docker
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import subprocess
import os
import traceback; 
import ast

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





def is_turtle_code(source: str) -> bool:
    tree = ast.parse(source)

    has_import = False
    has_usage  = False

    for node in ast.walk(tree):
        # 1) import turtle 또는 import turtle as t
        if isinstance(node, ast.Import):
            if any(alias.name == "turtle" for alias in node.names):
                has_import = True

        # 2) from turtle import forward 등
        if isinstance(node, ast.ImportFrom) and node.module == "turtle":
            has_import = True

        # 3) 실제 turtle.<something>() 호출
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "turtle":
                has_usage = True

    # import와 usage가 모두 있어야 turtle 코드로 본다
    return has_import and has_usage


# GUI 라이브러리 패턴
GUI_LIBS = [
    {"name":"turtle", "import": ["import turtle", "from turtle import"], "usage": ["turtle."]},
    {"name":"tkinter", "import": ["import tkinter", "from tkinter import"], "usage": ["Tk(", "Button(", "Canvas("]},
    {"name":"PyQt5", "import": ["from PyQt5 import", "import PyQt5"], "usage": ["QApplication(", "QMainWindow("]},
    {"name":"PySide2", "import": ["from PySide2 import", "import PySide2"], "usage": ["QApplication(", "QMainWindow("]},
    {"name":"wx", "import": ["import wx"], "usage": ["wx.App(", "wx.Frame("]},
    {"name":"kivy", "import": ["from kivy.app import App"], "usage": ["App("]},
    {"name":"PySimpleGUI", "import": ["import PySimpleGUI"], "usage": ["Window(", "Button("]},
    {"name":"pygame", "import": ["import pygame"], "usage": ["pygame.init(", "display.set_mode("]},
]

def detect_imports(source:str, patterns:list) -> bool:
    return any(pat in source for pat in patterns)


def detect_usage(source:str, patterns:list) -> bool:
    return any(pat in source for pat in patterns)


def is_gui_code(source: str) -> bool:
    # AST 파싱 시 syntax 오류 체크
    tree = ast.parse(source)
    for lib in GUI_LIBS:
        has_imp = detect_imports(source, lib["import"])
        has_use = detect_usage(source, lib["usage"])
        if has_imp and has_use:
            return True
    return False



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

      # 컨테이너 복사/kill
    subprocess.run(["docker","exec",DOCKER_NAME,"pkill","-f",f"python3 {remote_path}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["docker","cp",local_path,f"{DOCKER_NAME}:{remote_path}"])

    # # GUI 감지
    # try:
    #     gui_mode = is_gui_code(code)
    # except SyntaxError as e:
    #     return JSONResponse({"status":"error","type":"syntax","error":f"{e.msg} at line {e.lineno}"},status_code=400)

    # # 실행 및 에러 캡처
    # if gui_mode:
    #     # 테스트 실행으로 오류 확인
    #     try:
    #         # 먼저 cli로 실행해봄
    #         test = subprocess.run([
    #             "docker","exec",DOCKER_NAME,"python3",remote_path
    #         ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    #     except subprocess.TimeoutExpired:
    #         # 응답이 돌아오지 않아서 GUI가 실행되었다고 판단
    #         subprocess.Popen([
    #             "docker","exec","-e",f"DISPLAY={DOCKER_DISPLAY}",DOCKER_NAME,"python3",remote_path
    #         ])
    #         return JSONResponse({"status":"running","type":"gui"})

    #     if test.returncode != 0: # 에러 발생(예: NameError)
    #         return JSONResponse({"status":"error","type":"runtime","error":test.stderr.decode()},status_code=400)
        
    #     # 정상 test.returncode == 0 이면 → 에러 없이 종료(즉 GUI를 띄우지 않았거나, “종료 가능한” 스크립트)
    #     subprocess.Popen([
    #         "docker","exec","-e",f"DISPLAY={DOCKER_DISPLAY}",DOCKER_NAME,"python3",remote_path
    #     ])
    #     return JSONResponse({"status":"running","type":"gui"})
    # else:
    #     # CLI 모드
    #     result = subprocess.run([
    #         "docker","exec",DOCKER_NAME,"python3",remote_path
    #     ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    #     output = result.stdout.decode() + result.stderr.decode()
    #     return JSONResponse({"status":"done","type":"text","output":output})




    # turtle 코드인지 확인

    try:
        if is_turtle_code(code):
            
            # GUI 실행하기
            subprocess.Popen([
                "docker", "exec", "-e", f"DISPLAY={DOCKER_DISPLAY}",
                DOCKER_NAME, "python3", remote_path
            ])
            print("gui")
            return JSONResponse(
                status_code=201,
                content= {"status": "running", "type": "gui"}
            )
        else:
            # CLI 실행하기
            result = subprocess.run([
                "docker", "exec",
                DOCKER_NAME, "python3", remote_path
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            output = result.stdout.decode() + result.stderr.decode()
            # return {"status": "done", "type": "text", "output": output}
            print("cli")
            if "Traceback" in output:
                # 여기가 예외를 강제로 발생시키는 부분
                raise Exception(output)
        
            return JSONResponse(
                status_code=202,
                content= {"status": "running", "type": "cli", "output": output}
            )
        
    except Exception as e:
        # 예외 메시지를 문자열로 변환
        err_msg = str(e)
        err_msg = traceback.format_exc()

        if "No module named" in output:
            import re
            m = re.search(r"No module named ['\"]([^'\"]+)['\"]", err_msg)

            print(m.group(1),"을 다운받아야함")
            err_msg += f"{m.group(1)}을 다운받아야함"
        
        print("에러메시지: ", err_msg)

        return JSONResponse(
            status_code=500,
            content={"status": "error", "type": "cli", "output": err_msg}
        )

