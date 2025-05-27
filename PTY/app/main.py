from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import docker
import asyncio
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static", html=True), name="static")

client = docker.from_env()
CONTAINER_NAME = "vnc-webide"

class CodeRequest(BaseModel):
    code: str

@app.post("/run")
def run_code(req: CodeRequest):
    try:
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        return JSONResponse(status_code=404, content={"error": "Container not found"})

    safe_code = req.code.replace("'", "'\"'\"'")
    exec_cmd = f"echo '{safe_code}' > /tmp/user_code.py && DISPLAY=:1 python3 /tmp/user_code.py"
    container.exec_run(cmd=["bash", "-c", exec_cmd], detach=True)
    return {"status": "started"}

@app.get("/check-gui")
def check_gui_used():
    try:
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        return {"gui": False}

    exec_result = container.exec_run("test -f /tmp/gui_used.flag && echo yes || echo no")
    output = exec_result.output.decode().strip()
    return {"gui": output == "yes"}

@app.websocket("/ws")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()
    try:
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        await websocket.send_text("❌ 컨테이너 없음")
        await websocket.close()
        return

    exec_id = client.api.exec_create(container.id, cmd="/bin/bash", tty=True, stdin=True)
    sock = client.api.exec_start(exec_id, tty=True, stream=True, socket=True)

    loop = asyncio.get_event_loop()

    async def read_from_container():
        try:
            while True:
                output = await loop.run_in_executor(None, sock.recv, 1024)
                if output:
                    await websocket.send_text(output.decode(errors="ignore"))
        except Exception:
            await websocket.close()

    async def write_to_container():
        try:
            while True:
                data = await websocket.receive_text()
                if data.startswith("__code_exec__"):
                    _, code = data.split("__code_exec__", 1)
                    # GUI 감지 플래그 초기화
                    container.exec_run("rm -f /tmp/gui_used.flag")
                    wrapped_code = f"import os\nimport turtle\n{code}\nwith open('/tmp/gui_used.flag', 'w') as f: f.write('yes')\nturtle.done()"
                    shell_cmd = f"echo '{wrapped_code.replace("'", "'\\''")}' > temp.py && DISPLAY=:1 python3 temp.py"
                    await loop.run_in_executor(None, sock.send, (shell_cmd + "\n").encode())
                else:
                    await loop.run_in_executor(None, sock.send, data.encode())
        except WebSocketDisconnect:
            sock.close()

    await asyncio.gather(read_from_container(), write_to_container())