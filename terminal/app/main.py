# app/main.py
import os, socket, time, uuid, asyncio
from typing import AsyncGenerator, Dict, Tuple, List, Optional
from datetime import datetime
from urllib.parse import urlsplit

import docker, httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status, Request, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState
from pydantic import BaseModel

from config import FREE_MAX_CONTAINERS, DOCKER_DEFAULT_IMAGE, DOCKER_NETWORK, SPRING_BOOT_API_URL
from docker_client import get_docker
from roles import is_unlimited, ROLE_FREE
from security import get_current_user, AuthUser, _extract_bearer_token

# ---------- FastAPI ----------
app = FastAPI(title="WEB IDE API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적(선택)
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static", html=True), name="static")

# ---------- 공통 설정 ----------
docker_client = get_docker()
VNC_IMAGE = os.getenv("VNC_IMAGE", "webide-vnc")
CONTAINER_ENV_DEFAULT = {
    "VNC_PORT": "5901",
    "NOVNC_PORT": "6081",
    "VNC_GEOMETRY": "1024x768",
    "VNC_DEPTH": "24",
}
INTERNAL_NOVNC_PORT = 6081
venv_path = "/tmp/user_venv"
FIXED_WORKSPACE = "/opt/workspace"

# (cid, sid) -> PTY
sessions: Dict[Tuple[str, str], socket.socket] = {}
# ---------- 모델 ----------
class CreateContainerRequest(BaseModel):
    projectName: str
    image: Optional[str] = None
    cmd: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None

class CreateContainerResponse(BaseModel):
    id: str
    name: str
    image: str
    owner: str
    role: str
    limited_by_quota: bool
    projectName: str
    vnc_url: str
    ws_url: str

class CodeRequest(BaseModel):
    code: str
    tree: dict
    fileMap: dict
    run_code: str
    session_id: str
    container_id: str

class ContainerUrlsResponse(BaseModel):
    cid: str
    ws_url: str
    vnc_url: str

# ---------- 유틸 ----------
def _find_free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port

async def get_api_client(request: Request) -> AsyncGenerator[httpx.AsyncClient, None]:
    token = _extract_bearer_token(request)
    headers={"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=SPRING_BOOT_API_URL, headers=headers, timeout=10.0) as client:
        yield client

def _get_sendable_socket(sock):
    if hasattr(sock, "send") and hasattr(sock, "recv"):
        return sock
    if hasattr(sock, "_sock") and hasattr(sock._sock, "send"):
        return sock._sock
    raise RuntimeError("send 가능한 소켓이 없습니다.")

def _build_netloc_and_schemes(request: Request) -> tuple[str, str, str, str]:
    """return netloc, http_scheme, ws_scheme, host_only"""
    xf_host = request.headers.get("x-forwarded-host")
    host_hdr = request.headers.get("host")
    if xf_host:
        netloc = xf_host
    elif host_hdr:
        netloc = host_hdr
    else:
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        netloc = f"{request.client.host}:{port}"

    xf_proto = request.headers.get("x-forwarded-proto")
    http_scheme = xf_proto or request.url.scheme  # "http" or "https"
    ws_scheme = "wss" if http_scheme == "https" else "ws"
    host_only = urlsplit(f"//{netloc}", scheme="http").hostname or request.client.host
    return netloc, http_scheme, ws_scheme, host_only

def _resolve_container_id(container_id: str) -> str:
    """짧은 ID도 풀ID로 정규화"""
    try:
        c = docker_client.containers.get(container_id)
        return c.id
    except docker.errors.NotFound:
        for c in docker_client.containers.list(all=True):
            if c.id.startswith(container_id):
                return c.id
        raise

# ---------- 권한 ----------
def require_roles(*allowed: str):
    async def checker(user: AuthUser = Depends(get_current_user)):
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user
    return checker

@app.get("/me")
async def me(user: AuthUser = Depends(get_current_user)):
    return {"username": user.username, "role": user.role}

# ---------- 컨테이너 생성 ----------
@app.post("/containers", response_model=CreateContainerResponse, status_code=201)
async def create_container(
    body: CreateContainerRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
    api_client: httpx.AsyncClient = Depends(get_api_client)
):
    # 1) 할당량 확인
    if not is_unlimited(user.role):
        try:
            resp = await api_client.get(f"containers/count/{user.username}")
            resp.raise_for_status()
            count = resp.json().get("count", 0)
            if count >= FREE_MAX_CONTAINERS:
                raise HTTPException(status_code=429, detail="최대 생성 개수를 초과했습니다.")
        except httpx.RequestError as e:
            raise HTTPException(503, detail=f"데이터 서버 연결 실패: {e}")

    # 2) 포트 할당
    host_novnc_port = _find_free_port()

    # 3) 컨테이너 실행
    image = body.image or VNC_IMAGE
    env = dict(CONTAINER_ENV_DEFAULT)
    if body.env: env.update(body.env)

    while True:
        suffix = uuid.uuid4().hex[:8]
        name = f"{user.username}-{suffix}"
        try:
            docker_client.containers.get(name)
        except docker.errors.NotFound:
            break

    run_kwargs = {
        "name": name,
        "image": image,
        "detach": True,
        "environment": env,
        "ports": {f"{INTERNAL_NOVNC_PORT}/tcp": host_novnc_port},
    }
    if body.cmd: run_kwargs["command"] = body.cmd
    if DOCKER_NETWORK: run_kwargs["network"] = DOCKER_NETWORK

    try:
        container = docker_client.containers.run(**run_kwargs)
        container.reload()
    except Exception as e:
        raise HTTPException(500, detail=f"Docker 컨테이너 생성 실패: {e}")

    # 4) Spring DB 등록
    try:
        payload = {
            "containerId": container.id,
            "containerName": getattr(container, "name", ""),
            "ownerUsername": user.username,
            "imageName": image,
            "status": container.status,
            "projectName": body.projectName,
        }
        resp = await api_client.post("containers", json=payload)
        resp.raise_for_status()
    except httpx.RequestError:
        container.remove(force=True)
        raise HTTPException(500, detail="컨테이너 정보 등록 실패")

    # 5) URL 구성
    netloc, http_scheme, ws_scheme, host_only = _build_netloc_and_schemes(request)
    sid = uuid.uuid4().hex
    ws_url = f"{ws_scheme}://{netloc}/ws?cid={container.id}&sid={sid}"
    vnc_url = f"{http_scheme}://{host_only}:{host_novnc_port}/vnc.html?autoconnect=true&encrypt=0&resize=remote&password=jaewoo"

    return CreateContainerResponse(
        id=container.id[:12],
        name=getattr(container, "name", ""),
        image=image,
        owner=user.username,
        role=user.role,
        limited_by_quota=(user.role == ROLE_FREE),
        projectName=body.projectName,
        vnc_url=vnc_url,
        ws_url=ws_url,
    )

# ---------- 내 컨테이너 목록 ----------
@app.get("/containers/my")
async def list_my_containers(
    user: AuthUser = Depends(get_current_user),
    api_client: httpx.AsyncClient = Depends(get_api_client)
):
    try:
        resp = await api_client.get("containers")
        resp.raise_for_status()
        return resp.json()
    except httpx.RequestError as e:
        raise HTTPException(503, detail=f"데이터 서버에서 목록 조회 실패: {e}")

# ---------- 기존 컨테이너 재접속: ws_url / vnc_url 발급 ----------
@app.get("/containers/{container_id}/urls", response_model=ContainerUrlsResponse)
async def get_container_urls(
    container_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    try:
        full_id = _resolve_container_id(container_id)
        container = docker_client.containers.get(full_id)
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Container not found")

    # novnc host 포트(6081/tcp 바인딩) 확인
    try:
        ports = container.attrs["NetworkSettings"]["Ports"]
        bindings = ports.get("6081/tcp") or []
        host_port = bindings[0]["HostPort"] if bindings else None
    except Exception:
        host_port = None

    if not host_port:
        raise HTTPException(status_code=409, detail="noVNC port not published for this container")

    netloc, http_scheme, ws_scheme, host_only = _build_netloc_and_schemes(request)

    sid = uuid.uuid4().hex
    ws_url = f"{ws_scheme}://{netloc}/ws?cid={full_id}&sid={sid}"
    vnc_url = (
        f"{http_scheme}://{host_only}:{host_port}"
        "/vnc.html?autoconnect=true&encrypt=0&resize=remote&password=jaewoo"
    )
    return ContainerUrlsResponse(cid=full_id, ws_url=ws_url, vnc_url=vnc_url)

# ---------- WebSocket PTY ----------
@app.websocket("/ws")
async def websocket_terminal(
    websocket: WebSocket,
    cid: str = Query(..., alias="cid"),
    client_sid: Optional[str] = Query(None, alias="sid")
):
    await websocket.accept()

    # 풀 ID로 정규화
    try:
        full_id = _resolve_container_id(cid)
        container = docker_client.containers.get(full_id)
    except docker.errors.NotFound:
        await websocket.send_text("컨테이너가 없습니다.")
        await websocket.close()
        return

    if not client_sid:
        client_sid = uuid.uuid4().hex
    key = (full_id, client_sid)
    if key in sessions:
        await websocket.close(code=4409, reason="sid already in use")
        return

    await websocket.send_json({"sid": client_sid})

    # venv 보장
    ensure_venv = f"""
    set -e
    if [ ! -x '{venv_path}/bin/python' ]; then
        python3 -m venv '{venv_path}'
        '{venv_path}/bin/python' -m pip install --upgrade pip
    fi
    """
    container.exec_run(["bash","-lc", ensure_venv])

    # ✅ 더는 세션 전용 폴더를 만들지 않음
    # workspace = f"/opt/workspace/{client_sid}"  (삭제)

    # bash 인터랙티브 세션
    exec_id = docker_client.api.exec_create(
        container.id,
        cmd=[
            "bash", "-lc",
            f"source {venv_path}/bin/activate >/dev/null 2>&1 || true; "
            f"export PS1='webide:\\w$ '; exec bash --noprofile --norc -i"
        ],
        tty=True,
        stdin=True,
    )["Id"]

    sock = docker_client.api.exec_start(exec_id, tty=True, socket=True)
    pty = _get_sendable_socket(sock)
    sessions[key] = pty

    loop = asyncio.get_event_loop()

    async def reader():
        try:
            while True:
                data = await loop.run_in_executor(None, sock.recv, 1024)
                if not data:
                    break
                await websocket.send_text(data.decode(errors="ignore"))
        except Exception:
            pass

    async def writer():
        try:
            while True:
                msg = await websocket.receive_text()
                await loop.run_in_executor(None, sock.send, msg.encode())
        except WebSocketDisconnect:
            pass
        except RuntimeError:
            pass

    try:
        await asyncio.gather(reader(), writer())
    finally:
        try:
            sock.close()
            # ✅ 세션 종료 시 폴더/프로세스 정리 제거 (세션 전용 워크스페이스 없으므로)
            # container.exec_run(["bash","-lc", f"pkill -f '{workspace}' || true"])
            # container.exec_run(["bash","-lc", f"rm -rf '{workspace}'"])
        except Exception:
            pass
        sessions.pop(key, None)
        # workspaces.pop(key, None)  # 사용 안 함
        if websocket.application_state != WebSocketState.DISCONNECTED:
            await websocket.close()


# ---------- 코드 실행 ----------
@app.post("/run")
def run_code(req: CodeRequest):
    # 컨테이너 ID 풀ID로 정규화
    try:
        container = docker_client.containers.get(req.container_id)
    except docker.errors.NotFound:
        try:
            full_id = _resolve_container_id(req.container_id)
            container = docker_client.containers.get(full_id)
        except docker.errors.NotFound:
            return JSONResponse(status_code=404, content={"error": "Container not found"})

    full_id = container.id
    key = (full_id, req.session_id)

    pty = sessions.get(key)
    if not pty:
        raise HTTPException(400, "PTY 세션이 없습니다. 먼저 WS로 연결하세요.")

    try:
        # ✅ 세션별 폴더 대신 고정 워크스페이스 사용
        container.exec_run([
            "bash", "-lc",
            f"mkdir -p '{FIXED_WORKSPACE}' && find '{FIXED_WORKSPACE}' -mindepth 1 -delete"
        ])

        exec_path = _create_files_in_container(
            container, req.tree, req.fileMap, req.run_code, base_path=FIXED_WORKSPACE
        )
        if not exec_path:
            raise HTTPException(400, "실행 파일(run_code)을 찾지 못했습니다.")

        # 이전 실행 종료(고정 워크스페이스 기준)
        container.exec_run(["bash", "-lc", f"pkill -f '{FIXED_WORKSPACE}' || true"])

        # venv 파이썬 실행
        pty.send(f"{venv_path}/bin/python '{exec_path}'\n".encode())

        # GUI 체크
        for _ in range(5):
            check = container.exec_run(
                cmd=["bash", "-c", "DISPLAY=:1 xwininfo -root -tree | grep -E '\"[^ ]+\"' >/dev/null && echo yes || echo no"]
            )
            if b"yes" in check.output:
                return {"mode": "gui"}
            time.sleep(0.2)

        return {"mode": "cli"}
    except Exception as e:
        raise HTTPException(500, f"실행 실패: {e}")


# ---------- 파일 생성 로직 ----------
def _create_files_in_container(container, tree, fileMap, run_code, base_path="/opt", path=None):
    if path is None:
        path = []
    result = None

    if tree["type"] == "folder":
        folder_name = fileMap[tree["id"]]["name"]
        path.append(folder_name)
        full_path = base_path + "/" + "/".join(path)
        container.exec_run(cmd=["mkdir", "-p", full_path])
        for node in tree.get("children", []):
            sub = _create_files_in_container(container, node, fileMap, run_code, base_path, path)
            if sub: result = sub
        path.pop()

    elif tree["type"] == "file":
        file_name = fileMap[tree["id"]]["name"]
        content = fileMap[tree["id"]].get("content", "")
        full_path = base_path + "/" + "/".join(path + [file_name])
        if run_code == tree["id"]:
            result = full_path
        safe = content.replace("'", "'\"'\"'")
        container.exec_run(cmd=["bash", "-c", f"echo '{safe}' > '{full_path}'"])

    return result
