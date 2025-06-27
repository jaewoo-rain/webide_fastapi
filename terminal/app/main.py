import os
import time
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

# Docker 클라이언트 & 컨테이너 이름
client = docker.from_env()
CONTAINER_NAME = "vnc-webide"

# 정적 파일 서빙
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse("static/index.html")


class CodeRequest(BaseModel):
    code: str

# PTY 소켓 저장용
pty_socket = None

@app.post("/run")
def run_code(req: CodeRequest):
    global pty_socket
    if pty_socket is None:
        raise HTTPException(400, detail="PTY 세션이 준비되지 않았습니다. 먼저 /ws 로 연결하세요.")

    try: # 주어진 이름의 도커 컨테이너 가져오기
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        return JSONResponse(status_code=404, content={"error": "Container not found"})
    container.exec_run("pkill -f /tmp/user_code.py")

    # 안전하게 코드 파일로 만들 필요 없이, PTY에 바로 echo+실행 커맨드를 보냅니다.
    # 마지막에 '\n'이 있어야 bash가 실행 커맨드를 읽습니다.
    safe_code = req.code.replace("'", "'\"'\"'")
    cmd = f"echo '{safe_code}' > /tmp/user_code.py && python3 /tmp/user_code.py\n"
    try:
        pty_socket.send(cmd.encode())
        
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
        result = container.exec_run(cmd=["bash", "-c", "cat /tmp/out.log"])
        return {
            "mode": "cli",
            "output": result.output.decode(errors="ignore")
        }
    except Exception as e:
        raise HTTPException(500, detail=f"PTY 전송 실패: {e}")

@app.websocket("/ws")
async def websocket_terminal(websocket: WebSocket):
    global pty_socket
    await websocket.accept()  # 수락은 잘 되어 있음

    try:
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        await websocket.send_text("컨테이너가 없습니다.")
        await websocket.close()
        return

    # 가상환경 만들기
    venv_path = "/tmp/user_venv"
    container.exec_run(f"python3 -m venv {venv_path}")

    exec_id = client.api.exec_create(
        container.id,
        cmd="/bin/bash",
        # cmd=["bash", "-c", f"source {venv_path}/bin/activate && exec bash"], # 가상환경에서 실행하기
        tty=True,
        stdin=True
    )["Id"]

    sock = client.api.exec_start(
        exec_id,
        tty=True,
        socket=True
    )
    pty_socket = sock

    loop = asyncio.get_event_loop()

    async def read_from_container():
        try:
            while True:
                data = await loop.run_in_executor(None, sock.recv, 1024)
                # data = await loop.run_in_executor(None, sock._sock.recv, 1024)

                if not data:
                    break
                await websocket.send_text(data.decode(errors="ignore"))
        except Exception as e:
            print(f"[read] 예외: {e}")
        finally:
            await websocket.close()

    async def write_to_container():
        try:
            while True:
                msg = await websocket.receive_text()
                await loop.run_in_executor(None, sock.send, msg.encode())
                # await loop.run_in_executor(None, sock._sock.send, msg.encode())

        except WebSocketDisconnect:
            print("🔌 클라이언트 WebSocket 연결 종료")
        except RuntimeError as e:
            print(f"[write] RuntimeError: {e}")
        finally:
            try:
                sock.close()
            except Exception:
                pass
            pty_socket = None
            await websocket.close()

    try:
        await asyncio.gather(
            read_from_container(),
            write_to_container()
        )
    except Exception as e:
        print(f"[main] gather 예외 발생: {e}")
        await websocket.close()
