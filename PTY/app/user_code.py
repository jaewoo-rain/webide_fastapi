from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import docker
import asyncio

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = docker.from_env()
CONTAINER_NAME = "vnc-webide"

class CodeRequest(BaseModel):
    code: str

# 정적 파일 설정
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse("static/index.html")

@app.post("/run")
def run_code(req: CodeRequest):
    try:
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        return JSONResponse(status_code=404, content={"error": "Container not found"})

    # 안전한 코드 저장 및 실행
    safe_code = req.code.replace("'", "'\"'\"'")
    exec_cmd = f"echo '{safe_code}' > /tmp/user_code.py && DISPLAY=:1 python3 /tmp/user_code.py"
    container.exec_run(cmd=["bash", "-c", exec_cmd], detach=True)
    return {"status": "started"}

@app.websocket("/ws")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()
    try:
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        await websocket.send_text("❌ 컨테이너 없음")
        await websocket.close()
        return

    # exec_create로 bash PTY 세션 생성
    exec_id = client.api.exec_create(
        container.id,
        cmd="/bin/bash",
        tty=True,
        stdin=True
    )["Id"]

    # exec_start로 소켓 연결
    sock = client.api.exec_start(
        exec_id,
        tty=True,
        stream=False,
        socket=True
    )
    # sock 자체로 recv/send 사용

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

    await asyncio.gather(read_from_container(), write_to_container())
