import os
import docker
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse("static/index.html")

# Docker 클라이언트 & 컨테이너 이름
client = docker.from_env()
CONTAINER_NAME = "vnc-webide"

# PTY 소켓 저장용
pty_socket = None

class CodeRequest(BaseModel):
    code: str

@app.post("/run")
def run_code(req: CodeRequest):
    global pty_socket
    if pty_socket is None:
        raise HTTPException(400, detail="PTY 세션이 준비되지 않았습니다. 먼저 /ws 로 연결하세요.")

    # 안전하게 코드 파일로 만들 필요 없이, PTY에 바로 echo+실행 커맨드를 보냅니다.
    # 마지막에 '\n'이 있어야 bash가 실행 커맨드를 읽습니다.
    safe_code = req.code.replace("'", "'\"'\"'")
    cmd = f"echo '{safe_code}' > /tmp/user_code.py && python3 /tmp/user_code.py\n"
    try:
        pty_socket.send(cmd.encode())
    except Exception as e:
        raise HTTPException(500, detail=f"PTY 전송 실패: {e}")
    return {"status": "sent to PTY"}

@app.websocket("/ws")
async def websocket_terminal(websocket: WebSocket):
    global pty_socket
    await websocket.accept()

    # 컨테이너 가져오기
    try:
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        await websocket.send_text("❌ 컨테이너가 없습니다.")
        await websocket.close()
        return

    # bash PTY 세션 생성
    exec_id = client.api.exec_create(
        container.id,
        cmd="/bin/bash",
        tty=True,
        stdin=True
    )["Id"]

    # PTY 소켓 스트림 얻기
    sock = client.api.exec_start(
        exec_id,
        tty=True,
        socket=True
    )
    # Windows의 NpipeSocket도 sock.recv/send 로 동작
    pty_socket = sock  # 전역에 저장

    loop = asyncio.get_event_loop()

    async def read_from_container():
        try:
            while True:
                data = await loop.run_in_executor(None, sock.recv, 1024)
                if not data:
                    break
                await websocket.send_text(data.decode(errors="ignore"))
        except Exception:
            pass
        finally:
            await websocket.close()

    async def write_to_container():
        try:
            while True:
                msg = await websocket.receive_text()
                await loop.run_in_executor(None, sock.send, msg.encode())
        except WebSocketDisconnect:
            pass
        finally:
            sock.close()
            pty_socket = None

    # 읽기/쓰기 동시에 실행
    await asyncio.gather(read_from_container(), write_to_container())
