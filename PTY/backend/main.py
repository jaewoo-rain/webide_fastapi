from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess
import os
import time
import tempfile

app = FastAPI()

# ✅ CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CodeRequest(BaseModel):
    code: str

@app.post("/run-gui")
async def run_gui(req: CodeRequest):
    # 1️⃣ 코드 파일 임시 저장
    temp_dir = tempfile.gettempdir()
    code_path = os.path.join(temp_dir, "user_code.py")

    with open(code_path, "w") as f:
        f.write(req.code)

    # 2️⃣ DISPLAY=:1 환경으로 설정
    env = os.environ.copy()
    env["DISPLAY"] = ":1"

    # 3️⃣ Python GUI 코드 실행 (비동기 프로세스로 실행)
    subprocess.Popen(["python3", code_path], env=env)

    # 4️⃣ GUI 창 뜨는지 최대 30초까지 확인 (xwininfo 방식)
    for _ in range(30):
        time.sleep(1)
        try:
            output = subprocess.check_output(['xwininfo', '-root', '-tree'], env=env).decode()
            if "Canvas" in output or "Python Turtle Graphics" in output or "Tk" in output:
                return JSONResponse({
                    "status": "gui detected",
                    "novnc_url": "http://localhost:6080"
                })
        except subprocess.CalledProcessError:
            pass  # xwininfo 실패 시 무시하고 재시도

    return JSONResponse({
        "status": "no gui",
        "message": "GUI 창을 30초 내에 찾을 수 없습니다."
    })
