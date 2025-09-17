import os, uuid, socket, time, docker, httpx, asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends, status, Query

from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.websockets import WebSocketState
from uuid import uuid4
from typing import AsyncGenerator, Dict, Tuple, List, Optional
from security.security import get_current_user, AuthUser, _extract_bearer_token
from urllib.parse import urlsplit
from config import ROLE_ADMIN, ROLE_MEMBER, ROLE_FREE, FREE_MAX_CONTAINERS, DOCKER_NETWORK, VNC_IMAGE, CONTAINER_ENV_DEFAULT, INTERNAL_NOVNC_PORT, WORKSPACE, ALLOWED_NOVNC_PORTS
from docker_client import get_docker
from models import CodeRequest, CreateContainerRequest, CreateContainerResponse, ContainerUrlsResponse
from utils.util import get_api_client, _get_sendable_socket, _build_netloc_and_schemes, is_unlimited, create_file

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# == 공통 설정 == #
# Docker 클라이언트 & 컨테이너 이름
docker_client = get_docker()


venv_path = "/tmp/user_venv" # 가상환경 주소

# (cid, sid) -> PTY
sessions: Dict[Tuple[str, str], socket.socket] = {}
UNLIMITED_ROLES = {ROLE_MEMBER, ROLE_ADMIN}

# 짧은 도커 컨테이너 ID를 실제 전체 컨테이너 ID로 변환
def _resolve_container_id(container_id: str) -> str:
    # 1) 정확 조회
    try:
        return docker_client.containers.get(container_id).id
    except docker.errors.NotFound:
        pass

    # 2) prefix 매칭
    matches = [
        c.id for c in docker_client.containers.list(all=True)
        if c.id.startswith(container_id)
    ]

    if len(matches) == 1:
        return matches[0]
    elif len(matches) == 0:
        raise docker.errors.NotFound(f"No container matches id/prefix '{container_id}'")
    else:
        # 모호한 접두어
        raise RuntimeError(f"Ambiguous id prefix '{container_id}' matches {len(matches)} containers")

@app.get("/me")
async def me(user: AuthUser = Depends(get_current_user)):
    return {"username": user.username, "role": user.role}

# == 컨테이너 생성 == #
create_container_lock = asyncio.Lock()

# 이름으로 컨테이너 지우기
def _rm_container_by_name(name: str):
    try:
        for c in docker_client.containers.list(all=True, filters={"name": f"^{name}$"}):
            try:
                c.remove(force=True)
            except Exception:
                pass
    except Exception:
        pass

@app.post("/containers", response_model=CreateContainerResponse, status_code=201)
async def create_container(
    body: CreateContainerRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
    api_client: httpx.AsyncClient = Depends(get_api_client),
):
    # 1) FREE 사용자 제한
    if not is_unlimited(UNLIMITED_ROLES, user.role):
        try:
            resp = await api_client.get(f"internal/api/containers/count/{user.username}")
            resp.raise_for_status()
            if resp.json().get("count", 0) >= FREE_MAX_CONTAINERS:
                raise HTTPException(429, "최대 생성 개수를 초과했습니다.")
        except httpx.RequestError as e:
            raise HTTPException(503, detail=f"데이터 서버 연결 실패: {e}")

    image = body.image or VNC_IMAGE
    env = dict(CONTAINER_ENV_DEFAULT)
    if body.env:
        env.update(body.env)

    run_common = {
        "image": image,
        "detach": True,
        "environment": env,
    }
    if body.cmd:
        run_common["command"] = body.cmd
    if DOCKER_NETWORK:
        run_common["network"] = DOCKER_NETWORK

    container = None
    host_novnc_port = None
    last_err = None

    # 2) 락 안에서 이름/포트 재시도 + 실패 시 생성물 정리
    async with create_container_lock:
        for _ in range(50):  # 이름 재시도
            name = f"{user.username}-{uuid.uuid4().hex[:8]}"

            # 정확매치로 이름 중복 확인
            if docker_client.containers.list(all=True, filters={"name": f"^{name}$"}):
                continue

            for p in ALLOWED_NOVNC_PORTS:  # 포트 재시도
                try:
                    run_kwargs = {
                        **run_common,
                        "name": name,
                        "ports": {f"{INTERNAL_NOVNC_PORT}/tcp": p},  # 예: "6081/tcp": 10000
                    }
                    container = docker_client.containers.run(**run_kwargs)
                    container.reload()
                    host_novnc_port = p
                    break  # 포트 성공
                except docker.errors.APIError as e:
                    msg = str(e).lower()
                    last_err = e
                    # 포트 충돌 → 방금 생성된(시작 실패) 컨테이너 정리 후 다음 포트
                    if "port is already allocated" in msg:
                        _rm_container_by_name(name)
                        continue
                    # 이름 충돌(레이스) → 컨테이너 정리 후 새 이름 시도
                    if ("conflict" in msg and "name" in msg) or "name is already in use" in msg:
                        _rm_container_by_name(name)
                        container = None
                        break
                    # 그 외 오류는 즉시 실패
                    _rm_container_by_name(name)
                    raise HTTPException(500, detail=f"Docker run 실패: {e}") from e

            if container is not None:
                break  # 이름 루프 성공

    if container is None or host_novnc_port is None:
        raise HTTPException(503, detail=f"이름/포트 충돌로 컨테이너 생성 실패 (last: {last_err})")

    # 3) DB 등록 (실패 시 컨테이너 정리)
    try:
        payload = {
            "containerId": container.id,
            "containerName": getattr(container, "name", ""),
            "ownerUsername": user.username,
            "imageName": image,
            "status": container.status,
            "projectName": body.projectName,
            "port": host_novnc_port,
        }
        resp = await api_client.post("/internal/api/containers", json=payload)
        resp.raise_for_status()
    except httpx.RequestError as e:
        try:
            container.remove(force=True)
        except Exception:
            pass
        raise HTTPException(500, detail=f"컨테이너 정보 등록 실패: {e}") from e

    # 4) URL
    netloc, http_scheme, ws_scheme, host_only = _build_netloc_and_schemes(request)
    sid = uuid.uuid4().hex
    ws_url = f"{ws_scheme}://{netloc}/ws?cid={container.id}&sid={sid}"
    vnc_url = f"{http_scheme}://{host_only}:{host_novnc_port}/vnc.html?autoconnect=true&encrypt=0&resize=remote&password=jaewoo"

    # 5) 응답
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
        port=host_novnc_port,
    )




# == 내 컨테이너 목록 조회 == #
@app.get("/containers/my")
async def list_my_containers(
    user: AuthUser = Depends(get_current_user),
    api_client: httpx.AsyncClient = Depends(get_api_client)
):
    try:
        resp = await api_client.get("/internal/api/containers")
        resp.raise_for_status()
        return resp.json()
    except httpx.RequestError as e:
        raise HTTPException(503, detail=f"데이터 서버에서 목록 조회 실패: {e}")


# == 기존에 만들어둔 컨테이너 접속하기 == #
@app.get("/containers/{container_id}/urls", response_model=ContainerUrlsResponse)
async def get_container_urls(
    container_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    try: # 컨테이너 ID 정규화
        full_id = _resolve_container_id(container_id)
        container = docker_client.containers.get(full_id)
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Container not found")

    # novnc host 포트(6081/tcp 바인딩) 확인
    try:
        ports = container.attrs["NetworkSettings"]["Ports"]
        """
        ports = {
            "6081/tcp": [{ "HostIp": "0.0.0.0", "HostPort": "10025" }],
            "5901/tcp": [{ "HostIp": "0.0.0.0", "HostPort": "10026" }]
        }
        """
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





# (cid, sid) ─> (우리 앱의 세션 키) -> pty_socket ─> (Docker 내부)─> exec_id, TTY
@app.websocket("/ws")
async def websocket_terminal(
    websocket: WebSocket,
    cid: str = Query(..., alias="cid"), # 컨테이너 아이디
    client_sid: Optional[str] = Query(None, alias="sid") # 터미널 세션 식별자
):
    await websocket.accept()  # 수락

    # 풀 ID로 정규화
    try:
        full_id = _resolve_container_id(cid)
        container = docker_client.containers.get(full_id)
    except docker.errors.NotFound:
        await websocket.send_text("컨테이너가 없습니다.")
        await websocket.close()
        return
    
    # cid, sid 이용해서 세션 만들어 넣기
    if not client_sid:
        client_sid = uuid.uuid4().hex
    key = (full_id, client_sid)
    if key in sessions:
        await websocket.close(code=4409, reason="sid already in use")
        return

    await websocket.send_json({"sid": client_sid}) # 클라이언트에게 sid 정보 공유하기

    # venv 보장
    ensure_venv = f"""
    set -e
    if [ ! -x '{venv_path}/bin/python' ]; then
        python3 -m venv '{venv_path}'
        '{venv_path}/bin/python' -m pip install --upgrade pip
    fi
    """
    container.exec_run(["bash","-lc", ensure_venv])


    # bash 인터랙티브 세션
    exec_id = docker_client.api.exec_create(
        container.id,
        cmd=[ # 컨테이너 안에서 실행할 명령어 : bash 셸을 실행하겠다 -> 컨테이너 안에 새로운 bash 터미널을 띄워서 상호작용할 수 있게 준비
            "bash", "-lc",
            f"source {venv_path}/bin/activate >/dev/null 2>&1 || true; "
            f"export PS1='webide:\\w$ '; exec bash --noprofile --norc -i"
        ],
        tty=True,  # 표준 입력을 받을 수 있게 하겠다
        stdin=True,
    )["Id"] # exec 세션의 고유 ID

    # exec_id을 이용해서 실행, sock은 바이너리 데이터 입출력을 위한 소켓 객체
    sock = docker_client.api.exec_start(exec_id, tty=True, socket=True)

    # 현재 소켓 저장 -> run 함수 실행을 위해 전역으로 다룸
    pty = _get_sendable_socket(sock)
    sessions[key] = pty # 세션 등록

    # 현재 비동기 루프(이벤트 루프)를 가져옴. 여기에 blocking 작업을 offload할 때 사용.
    loop = asyncio.get_event_loop()

    # 데이터를 클라이언트에게 보내기
    async def reader():
        try:
            while True:
                data = await loop.run_in_executor(None, sock.recv, 1024) # sock.recv(1024)가 blocking I/O이므로 run_in_executor를 통해 별도 스레드에서 실행, 1024 바이트씩 데이터 읽음
                if not data:
                    break
                await websocket.send_text(data.decode(errors="ignore"))
        except Exception:
            pass

    # 데이터를 컨테이너에게 보내기
    async def writer():
        try:
            while True:
                msg = await websocket.receive_text()
                await loop.run_in_executor(None, sock.send, msg.encode()) # 받은 메시지를 바이너리로 인코딩 후 sock.send()로 bash 입력에 전달
        except WebSocketDisconnect:
            print("🔌 클라이언트 WebSocket 연결 종료")
        except RuntimeError:
            print(f"[write] RuntimeError: {e}")

    # 소켓 실행
    try:
        await asyncio.gather(reader(), writer()) # 읽기, 쓰기 병행 실행
    except Exception as e:
        print(f"[main] gather 예외 발생: {e}")
        # await websocket.close()
    finally:
        try:
            sock.close()
        except Exception as e:
            print(f"소켓 종료 실패: {e}")
        sessions.pop(key, None)

        if websocket.application_state != WebSocketState.DISCONNECTED:  # 상태 체크 추가
            await websocket.close()
    

# == 코드 실행 == #
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
    pty = sessions.get(key) # 세션이용해서 PTY 연결하기

    if not pty:
        raise HTTPException(400, detail="PTY 세션이 준비되지 않았습니다. 먼저 /ws 로 연결하세요.")

    try:
        container.exec_run([
            "bash", "-lc",
            f"mkdir -p '{WORKSPACE}' && find '{WORKSPACE}' -mindepth 1 -delete"
        ])

        # 파일 생성
        exec_path = create_file(container, req.tree, req.fileMap, req.run_code, base_path=WORKSPACE)
        if not exec_path:
            raise HTTPException(400, "실행 파일(run_code)을 찾지 못했습니다.")
    
        # 이전 실행 종료
        container.exec_run(["bash", "-lc", f"pkill -f '{WORKSPACE}' || true"])

        # venv 파이썬으로 실행 (명시적으로)
        pty.send(f"{venv_path}/bin/python '{exec_path}'\n".encode())

        # 최대 2초 (0.2초 * 10번) 동안 GUI 실행 여부를 확인
        for _ in range(5):
            check = container.exec_run( 
                cmd=["bash", "-c", "DISPLAY=:1 xwininfo -root -tree | grep -E '\"[^ ]+\"' && echo yes || echo no"]
            )
            # 루트 트리에 GUI 창이 존재하는지 체크
            if b"yes" in check.output:
                return {"mode": "gui"}
            time.sleep(0.2)

        # CLI 모드 결과 
        return {"mode": "cli"}
    except Exception as e:
        raise HTTPException(500, detail=f"PTY 전송 실패: {e}")

