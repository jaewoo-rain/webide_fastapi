from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import subprocess
import os
import time

app = FastAPI()

class CodeRequest(BaseModel):
    code: str

@app.post("/run-gui")
async def run_gui(req: CodeRequest):
    # 1. 코드 저장
    with open("user_code.py", "w") as f:
        f.write(req.code)

    # 2. DISPLAY 환경 설정 (VNC 화면을 의미)
    env = os.environ.copy()
    env["DISPLAY"] = ":1"

    # 3. GUI 코드 실행 (백그라운드)
    subprocess.Popen(["python3", "user_code.py"], env=env)

    # 4. GUI 감지 (최대 30초 대기)
    for _ in range(30):
        try:
            output = subprocess.check_output(['xwininfo', '-root', '-tree'], env=env).decode()
            if '("'.encode() in output.encode():
                return JSONResponse({
                    "status": "gui detected",
                    "novnc_url": "http://localhost:6081"
                })
        except Exception:
            pass
        time.sleep(1)

    return JSONResponse({
        "status": "no gui",
        "message": "GUI not detected after 30s"
    })
