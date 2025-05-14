from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import subprocess
import uuid
import os

app = FastAPI()

# Docker 컨테이너 이름
DOCKER_NAME = "my-ubuntu"
DOCKER_DISPLAY = ":1"  # VNC 디스플레이 번호

@app.post('/run')
async def run_code(request: Request):
    body = await request.json()
    code = body.get("code")
    if not code:
        return JSONResponse(content={"error": "No code provided"}, status_code=400)

    # 1. 임시 파일로 저장
    filename = f"temp_{uuid.uuid4().hex}.py"
    local_path = os.path.join(os.getcwd(), filename)
    with open(local_path, "w") as f:
        f.write(code)

    # 2. Docker로 복사
    remote_path = f"/tmp/{filename}"
    subprocess.run(["docker", "cp", local_path, f"{DOCKER_NAME}:{remote_path}"])

    # 3. Docker에서 실행 (백그라운드로)
    subprocess.Popen([
        "docker", "exec", "-e", f"DISPLAY={DOCKER_DISPLAY}",
        DOCKER_NAME, "python3", remote_path
    ])

    return {"status": "running", "file": remote_path}

# 실행 명령 예시
# uvicorn 파일명:app --reload --host 0.0.0.0 --port 5000
# 예: uvicorn main:app --reload --host 0.0.0.0 --port 5000
