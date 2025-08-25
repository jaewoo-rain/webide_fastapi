import os
import socket
import time
import docker
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.websockets import WebSocketState
from uuid import uuid4

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Docker 클라이언트 & 컨테이너 이름
client = docker.from_env()
CONTAINER_NAME = "vnc-webide"
venv_path = "/tmp/user_venv" # 나중에 동적으로 이름 바꿔야하나?

# PTY 소켓 저장용
sessions = {} # sid -> PTY socket
workspaces = {}

class CodeRequest(BaseModel):
    code: str
    tree: object
    fileMap: object
    run_code: str
    session_id: str

# 정적 파일 서빙
app.mount("/static", StaticFiles(directory="static", html=True), name="static")
app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")

@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse("static/index.html")

@app.get("/frontend")
def read_index():
    return FileResponse("frontend/dist/index.html")

# 안전한 socket 추출 함수
def get_sendable_socket(sock):
    if hasattr(sock, "send") and hasattr(sock, "recv"):
        return sock
    elif hasattr(sock, "_sock") and hasattr(sock._sock, "send"):
        return sock._sock
    else:
        raise RuntimeError("send 가능한 소켓이 없습니다.")
    
@app.post("/run")
def run_code(req: CodeRequest):
    tree = req.tree
    fileMap = req.fileMap
    run_code = req.run_code
    session_id = req.session_id

    pty = sessions.get(session_id)

    if not pty:
        raise HTTPException(400, detail="PTY 세션이 준비되지 않았습니다. 먼저 /ws 로 연결하세요.")

    try: # 주어진 이름의 도커 컨테이너 가져오기
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        return JSONResponse(status_code=404, content={"error": "Container not found"})
    
    
    try:
        # 세션별 워크스페이스 초기화(자기 것만)
        workspace = f"/opt/workspace/{req.session_id}"
        container.exec_run(["bash", "-lc", f"mkdir -p '{workspace}' && find '{workspace}' -mindepth 1 -delete"])

        # 파일 생성
        exec_path = createFile(container, req.tree, req.fileMap, req.run_code, base_path=workspace)
        if not exec_path:
            raise HTTPException(400, "실행 파일(run_code)을 찾지 못했습니다.")

        # 이전 실행 종료(세션 범위로 제한)
        container.exec_run(["bash", "-lc", f"pkill -f '{workspace}' || true"])

        # venv 파이썬으로 실행 (명시적으로)
        pty.send(f"{venv_path}/bin/python '{exec_path}'\n".encode())


        # 최대 2초 (0.2초 * 10번) 동안 GUI 실행 여부를 확인
        for _ in range(5):
            check = container.exec_run( 
                cmd=["bash", "-c", "DISPLAY=:1 xwininfo -root -tree | grep -E '\"[^ ]+\"' && echo yes || echo no"]
            )
            # 루트 트리에 GUI 창이 존재하는지 체크
            if b"yes" in check.output:
                return {
                    "mode": "gui",
                    "url": "http://localhost:6081/vnc.html?autoconnect=true&encrypt=0&resize=remote&password=jaewoo"
                }
            time.sleep(0.2)

        # CLI 모드 결과 
        # result = container.exec_run(cmd=["bash", "-c", "cat /tmp/out.log"])
        return {
            "mode": "cli",
            # "output": result.output.decode(errors="ignore")
        }
    except Exception as e:
        raise HTTPException(500, detail=f"PTY 전송 실패: {e}")

@app.websocket("/ws")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()  # 수락
    
    client_sid = websocket.query_params.get("sid")
    if client_sid and client_sid in sessions:
        await websocket.close(code=4409, reason="sid already in use")
        return
    sid = client_sid or str(uuid4())

    await websocket.send_json({"sid": sid})  # 클라이언트에게 알려줌

    try:
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        await websocket.send_text(" 컨테이너가 없습니다.")
        await websocket.close()
        return

    # venv 보장
    ensure_venv = f"""
    set -e
    if [ ! -x '{venv_path}/bin/python' ]; then
    python3 -m venv '{venv_path}'
    '{venv_path}/bin/python' -m pip install --upgrade pip
    fi
    """
    container.exec_run(["bash","-lc", ensure_venv])

    # 세션 전용 워크스페이스 생성 & 등록
    workspace = f"/opt/workspace/{sid}"
    container.exec_run(["bash","-lc", f"mkdir -p '{workspace}'"])
    workspaces[sid] = workspace

    exec_id = client.api.exec_create( # 실제 실행을 하지는 않고, 실행 준비만 하고 exec ID를 생성해줌
        container.id,
        # cmd="/bin/bash", # 컨테이너 안에서 실행할 명령어 : bash 셸을 실행하겠다 -> 컨테이너 안에 새로운 bash 터미널을 띄워서 상호작용할 수 있게 준비
        cmd=["bash", "-c", f"source {venv_path}/bin/activate && exec bash"],
        tty=True, 
        stdin=True  # 표준 입력을 받을 수 있게 하겠다
    )["Id"] # exec 세션의 고유 ID

    # exec_id을 이용해서 실행, sock은 바이너리 데이터 입출력을 위한 소켓 객체
    sock = client.api.exec_start(
        exec_id,
        tty=True,
        socket=True
    )

    # 현재 소켓 저장 -> run 함수 실행을 위해 전역으로 다룸
    pty = get_sendable_socket(sock)
    sessions[sid] = pty # pty 등록하기

    # 현재 비동기 루프(이벤트 루프)를 가져옴. 여기에 blocking 작업을 offload할 때 사용.
    loop = asyncio.get_event_loop()

    # 데이터를 클라이언트에게 보내기기
    async def read_from_container():
        try:
            while True:
                try:
                    data = await loop.run_in_executor(None, sock.recv, 1024) # sock.recv(1024)가 blocking I/O이므로 run_in_executor를 통해 별도 스레드에서 실행, 1024 바이트씩 데이터 읽음
                    if not data:
                        break
                    await websocket.send_text(data.decode(errors="ignore"))
                except socket.timeout: # 타임아웃 되더라도 계속 실행함
                    print("[read] recv timed out, but continuing...")
                    continue
        except Exception as e:
            print(f"[read] 예외: {e}")



    # 데이터를 컨테이너에게 보내기
    async def write_to_container():
        try:
            while True:
                msg = await websocket.receive_text()
                await loop.run_in_executor(None, sock.send, msg.encode()) # 받은 메시지를 바이너리로 인코딩 후 sock.send()로 bash 입력에 전달달
                # await loop.run_in_executor(None, sock._sock.send, msg.encode())

        except WebSocketDisconnect:
            print("🔌 클라이언트 WebSocket 연결 종료")
        except RuntimeError as e:
            print(f"[write] RuntimeError: {e}")

    try:
        await asyncio.gather(  # 읽기, 쓰기 병행 실행
            read_from_container(),
            write_to_container()
        )
    except Exception as e:
        print(f"[main] gather 예외 발생: {e}")
        # await websocket.close()
    finally:
        try:
            sock.close()
            container.exec_run(["bash","-lc", f"pkill -f '{workspace}' || true"])
            container.exec_run(["bash","-lc", f"rm -rf '{workspace}'"])
        except Exception as e:
            print(f"소켓 종료 실패: {e}")
        sessions.pop(sid, None) 

        if websocket.application_state != WebSocketState.DISCONNECTED:  # 상태 체크 추가
            await websocket.close()



def createFile(container, tree, fileMap, run_code, base_path="/opt", path=None):
    if path is None:
        path = []

    result = None  # 최종 실행 파일 경로 저장

    if tree["type"] == "folder":
        folder_name = fileMap[tree["id"]]["name"]
        print("-- \n경로:", "/".join(path))
        path.append(folder_name)
        full_path = base_path + "/" + "/".join(path)

        print(f"+ 폴더생성 {folder_name}")
        container.exec_run(cmd=["mkdir", "-p", full_path])

        for node in tree.get("children", []):
            sub_result = createFile(container, node, fileMap, run_code, base_path, path)
            if sub_result:
                result = sub_result  # 하위 트리에서 실행파일 발견 시 저장

        path.pop()

    elif tree["type"] == "file":
        file_name = fileMap[tree["id"]]["name"]
        content = fileMap[tree["id"]].get("content", "")
        print("-- \n경로:", "/".join(path))
        print(f"+ 파일생성 {file_name} (내용: {content}) (id: {tree['id']})")

        full_path = base_path + "/" + "/".join(path + [file_name])

        if run_code == tree["id"]:
            print("=====실행파일====")
            print(full_path)
            print("=================")
            result = full_path  # 실행파일 경로 저장

        safe_content = content.replace("'", "'\"'\"'")
        container.exec_run(cmd=["bash", "-c", f"echo '{safe_content}' > '{full_path}'"])

    return result  # 실행 파일 경로 반환
