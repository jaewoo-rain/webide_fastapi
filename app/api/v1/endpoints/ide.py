from fastapi import FastAPI
from fastapi import APIRouter
from app.schemas.ide import CodeRequest
import docker
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.core import docker_client

router = APIRouter(
    prefix="/ide",
    tags=["ide"]
)

@router.post("/run")
async def run_code(req: CodeRequest):
    global pty_socket
    if pty_socket is None:
        raise HTTPException(400, detail="PTY 세션이 준비되지 않았습니다. 먼저 /ws 로 연결하세요.")
    
    # 기존 코드 죽이기기
    try: # 주어진 이름의 도커 컨테이너 가져오기
        container = docker_client.containers.get(docker_client.CONTAINER_NAME)
    except docker.errors.NotFound:
        return JSONResponse(status_code=404, content={"error": "Container not found"})
    container.exec_run("pkill -f /tmp/user_code.py")




    safe_code = req.code.replace("'", "'\"'\"'")
    cmd = f"echo '{safe_code}' > /tmp/user_code.py && python3 /tmp/user_code.py\n"

    try:
        await asyncio.get_event_loop().run_in_executor(
            None,
            pty_socket._sock.send,  # ✅ ._sock 확실히 사용
            cmd.encode()
        )

    except Exception as e:
        print(f"[run_code] 에러: {e}")
        raise HTTPException(500, detail=f"PTY 전송 실패: {e}")

    return {"status": "sent to PTY"}