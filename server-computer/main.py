# import os
import docker
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.websockets import WebSocketState
import socket

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


# 안전한 socket 추출 함수
def get_sendable_socket(sock):
    if hasattr(sock, "send") and hasattr(sock, "recv"):
        return sock
    elif hasattr(sock, "_sock") and hasattr(sock._sock, "send"):
        return sock._sock
    else:
        raise RuntimeError("send 가능한 소켓이 없습니다.")


@app.post("/run")
async def run_code(req: CodeRequest):
    global pty_socket
    if pty_socket is None:
        raise HTTPException(400, detail="PTY 세션이 준비되지 않았습니다. 먼저 /ws 로 연결하세요.")

    try:
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        return JSONResponse(status_code=404, content={"error": "Container not found"})

    container.exec_run("pkill -f /tmp/user_code.py")

    safe_code = req.code.replace("'", "'\"'\"'")
    cmd = f"echo '{safe_code}' > /tmp/user_code.py && python3 /tmp/user_code.py\n"

    try:
        await asyncio.get_event_loop().run_in_executor(
            None,
            pty_socket.send,
            cmd.encode()
        )
    except Exception as e:
        print(f"[run_code] 에러: {e}")
        raise HTTPException(500, detail=f"PTY 전송 실패: {e}")

    return {"status": "sent to PTY"}


@app.websocket("/ws")
async def websocket_terminal(websocket: WebSocket):
    global pty_socket
    await websocket.accept()

    try:
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        await websocket.send_text(" 컨테이너가 없습니다.")
        await websocket.close()
        return

    # bash 세션 실행
    exec_id = client.api.exec_create(
        container.id,
        cmd="/bin/bash",
        tty=True,
        stdin=True
    )["Id"]

    sock = client.api.exec_start(
        exec_id,
        tty=True,
        socket=True
    )

    # 안전한 send/recv 가능한 소켓 추출
    raw_sock = get_sendable_socket(sock)
    pty_socket = raw_sock

    print(f"[DEBUG] raw_sock type: {type(raw_sock)}", flush=True)

    loop = asyncio.get_event_loop()

    async def read_from_container():
        try:
            while True:
                data = await loop.run_in_executor(None, raw_sock.recv, 1024)
                if not data:
                    break
                await websocket.send_text(data.decode(errors="ignore"))
        except Exception as e:
            print(f"[read] 예외: {e}")

    async def read_from_container():
        try:
            while True:
                try:
                    data = await loop.run_in_executor(None, raw_sock.recv, 1024)
                    if not data:
                        break
                    await websocket.send_text(data.decode(errors="ignore"))
                except socket.timeout:
                    print("[read] recv timed out, but continuing...")
                    continue
        except Exception as e:
            print(f"[read] 예외: {e}")

    async def write_to_container():
        try:
            while True:
                msg = await websocket.receive_text()
                await loop.run_in_executor(None, raw_sock.send, msg.encode())
        except WebSocketDisconnect:
            print(" 클라이언트 WebSocket 연결 종료")
        except RuntimeError as e:
            print(f"[write] RuntimeError: {e}")

    try:
        await asyncio.gather(
            read_from_container(),
            write_to_container()
        )
    except Exception as e:
        print(f"[main] gather 예외 발생: {e}")
    finally:

        try:
            raw_sock.close()
        except Exception:
            pass
        pty_socket = None
        if websocket.application_state != WebSocketState.DISCONNECTED:  # 상태 체크 추가
            await websocket.close()