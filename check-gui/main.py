import subprocess
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import docker
import time

app = FastAPI()

# CORS 허용 설정 - 모든 출처에서의 접근을 허용
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

@app.get("/")
def serve_index():
    return FileResponse("static/index.html")

class CodeRequest(BaseModel):
    code: str

@app.post("/run")
def run_code(req: CodeRequest):
    try: # 주어진 이름의 도커 컨테이너 가져오기
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        return JSONResponse(status_code=404, content={"error": "Container not found"})


    # # 기존 프로세스 죽이기
    # subprocess.run([
    #     "docker", "exec", CONTAINER_NAME,
    #     "pkill", "-f", f"python3 /tmp/user_code.py"
    # ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 컨테이너 내부에서 이전 실행 중인 Python 코드 프로세스를 종료
    container.exec_run("pkill -f /tmp/user_code.py")

    # 클라이언트가 보낸 코드를 안전하게 escape 처리하여 컨테이너 내부에 저장
    safe_code = req.code.replace("'", "'\"'\"'")  # bash에서 ' 안 끊기게 escaping
    container.exec_run(cmd=["bash", "-c", f"echo '{safe_code}' > /tmp/user_code.py"])

    # 컨테이너 내부에서 DISPLAY=:1 설정으로 GUI 실행 준비
    # 실행 결과 로그 저장되고 백그라운드로 실행
    exec_cmd = "DISPLAY=:1 python3 /tmp/user_code.py > /tmp/out.log 2>&1 &"
    container.exec_run(cmd=["bash", "-c", exec_cmd])

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
