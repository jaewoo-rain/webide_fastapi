from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import docker
import time

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

@app.get("/")
def serve_index():
    return FileResponse("static/index.html")

class CodeRequest(BaseModel):
    code: str

@app.post("/run")
def run_code(req: CodeRequest):
    try: # 도커 컨테이너 가져오기
        container = client.containers.get(CONTAINER_NAME)
    except docker.errors.NotFound:
        return JSONResponse(status_code=404, content={"error": "Container not found"})

    
    # 이전 실행 중인 Python 코드 프로세스를 종료
    container.exec_run("pkill -f /tmp/user_code.py")

    # 클라이언트가 보낸 코드를 안전하게 escape 처리하여 컨테이너 내부에 저장
    safe_code = req.code.replace("'", "'\"'\"'")
    container.exec_run(cmd=["bash", "-c", f"echo '{safe_code}' > /tmp/user_code.py"])

    # 컨테이너 내부에서 DISPLAY=:1 설정으로 GUI 실행 준비
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

    """
import turtle

# 화면 설정
screen = turtle.Screen()
screen.title("Turtle Spiral Demo")
screen.bgcolor("white")
screen.setup(width=600, height=600)

# 거북이(터틀) 설정
spiral = turtle.Turtle()
spiral.speed(0)          # 최고 속도
spiral.width(2)          # 선 굵기

colors = ["red", "orange", "yellow", "green", "blue", "purple"]

# 나선 그리기
for i in range(360):
    spiral.pencolor(colors[i % len(colors)])
    spiral.forward(i * 0.5)
    spiral.right(59)

# 클릭하면 종료
screen.exitonclick()
    """