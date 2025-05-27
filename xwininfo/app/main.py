from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import docker
import time

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 설정
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

# Docker 컨테이너 설정
client = docker.from_env()
CONTAINER_NAME = "vnc-webide"

@app.get("/")
def serve_index():
    return FileResponse("static/index.html")


class CodeRequest(BaseModel):
    code: str


@app.post("/run")
def run_code(req: CodeRequest):
    try:
        container = client.containers.get(CONTAINER_NAME)
        if container.status != "running":
            container.start()
    except docker.errors.NotFound:
        return JSONResponse(status_code=404, content={"error": "Container not found"})

    code = req.code
    safe_code = code.replace("'", "'\"'\"'")

    # GUI 플래그 초기화
    container.exec_run("rm -f /tmp/gui_used.flag")

    # 코드 작성 및 실행
    full_code = f"with open('/tmp/gui_used.flag', 'w') as f: f.write('yes')\n{code}"
    wrapped_code = full_code.replace("'", "'\"'\"'")
    exec_cmd = f"echo '{wrapped_code}' > /tmp/user_code.py && DISPLAY=:1 python3 /tmp/user_code.py"
    container.exec_run(cmd=["bash", "-c", exec_cmd], detach=True)

    # GUI 감지 시도
    for _ in range(10):
        time.sleep(0.2)
        check = container.exec_run("test -f /tmp/gui_used.flag && echo yes || echo no")
        if b"yes" in check.output:
            return {
                "mode": "gui",
                "url": "http://localhost:6081/vnc.html?autoconnect=true&encrypt=0&resize=remote&password=jaewoo"
            }

    # CLI 실행 결과 반환
    result = container.exec_run(cmd=["bash", "-c", f"python3 -c '{safe_code}'"], stdout=True, stderr=True)
    output = result.output.decode(errors="ignore")
    return {"mode": "cli", "output": output}
