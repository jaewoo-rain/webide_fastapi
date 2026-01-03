import uuid, socket, time, httpx, asyncio, json
from pathlib import Path
from typing import Dict, Tuple, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends, status, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from kubernetes import client, config
from kubernetes.stream import stream

from security.security import get_current_user, AuthUser
from config import (ROLE_ADMIN, ROLE_MEMBER, ROLE_FREE, FREE_MAX_CONTAINERS, 
                    VNC_IMAGE, CONTAINER_ENV_DEFAULT, INTERNAL_NOVNC_PORT, 
                    WORKSPACE, ALLOWED_NOVNC_PORTS)

# 모델 관련 import
from models.CodeRequest import CodeRequest
from models.CreateContainerRequest import CreateContainerRequest
from models.CreateContainerResponse import CreateContainerResponse
from models.ContainerUrlsResponse import ContainerUrlsResponse
from models.FileStructureResponse import FileStructureResponse
from models.CodeSaveRequest import CodeSaveRequest
from models.FileDeleteRequest import FileDeleteRequest 
from models.RenameFileRequest import RenameFileRequest
from models.RenameProjectRequest import RenameProjectRequest

from k8s_vnc import create_vnc_pod_and_service, delete_vnc_pod_and_service, get_vnc_node_port
from utils.util import get_api_client, _build_netloc_and_schemes, is_unlimited, create_file

app = FastAPI()

# K8s 클러스터 인증 로드
try:
    config.load_incluster_config()
except:
    config.load_kube_config()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# == 공통 변수 및 유틸리티 == #
venv_path = "/tmp/user_venv"
# (cid, sid) -> PTY 역할을 하는 스트림 객체 보관용 (있을 경우만 사용)
sessions: Dict[Tuple[str, str], any] = {}
UNLIMITED_ROLES = {ROLE_MEMBER, ROLE_ADMIN}

def k8s_exec_run(pod_name: str, command: List[str]) -> str:
    v1 = client.CoreV1Api()
    try:
        # tty=False여야 실행 결과를 텍스트로 온전히 가져오기 쉽습니다.
        resp = stream(
            v1.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace="webide-net",
            command=command,
            stderr=True, stdin=False, stdout=True, tty=False,
            _preload_content=True
        )
        
        output = ""
        while resp.is_open():
            resp.update(timeout=1)
            if resp.peek_stdout():
                output += resp.read_stdout()
            if not resp.is_open():
                break
        resp.close()
        return output
    except Exception as e:
        print(f"❌ [K8S EXEC ERROR] {pod_name}: {e}")
        return ""

@app.get("/me")
async def me(user: AuthUser = Depends(get_current_user)):
    return {"username": user.username, "role": user.role}

@app.get("/test")
def test():
    return "test"

# == 컨테이너 생성 == #
create_container_lock = asyncio.Lock()

@app.post("/containers", response_model=CreateContainerResponse, status_code=201)
async def create_container(
    body: CreateContainerRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
    api_client: httpx.AsyncClient = Depends(get_api_client),
):
    if not is_unlimited(UNLIMITED_ROLES, user.role):
        resp = await api_client.get(f"internal/api/containers/count/{user.username}")
        if resp.json().get("count", 0) >= FREE_MAX_CONTAINERS:
            raise HTTPException(429, "최대 생성 개수를 초과했습니다.")

    image = body.image or VNC_IMAGE
    image = "jaewoo6257/vnc:1.0.0" # 고정 이미지 사용

    env = dict(CONTAINER_ENV_DEFAULT)
    if body.env: env.update(body.env)

    pod_name, host_novnc_port = None, None
    async with create_container_lock:
        for p in ALLOWED_NOVNC_PORTS:
            try:
                res = create_vnc_pod_and_service(
                    username=user.username, image=image, env=env,
                    internal_vnc_port=INTERNAL_NOVNC_PORT, node_port=p,
                    project_name=body.projectName
                )
                pod_name, host_novnc_port = res["pod_name"], res["node_port"]
                break
            except: continue

    if not pod_name: raise HTTPException(503, detail="포트 충돌로 VNC Pod 생성 실패")

    try:
        payload = {
            "containerId": pod_name, "containerName": pod_name,
            "ownerUsername": user.username, "imageName": image,
            "status": "Running", "projectName": body.projectName, "port": host_novnc_port,
        }
        resp = await api_client.post("/internal/api/containers", json=payload)
        resp.raise_for_status()
    except Exception as e:
        delete_vnc_pod_and_service(pod_name)
        raise HTTPException(500, detail=f"DB 등록 실패: {e}")

    netloc, http_scheme, _, host_only = _build_netloc_and_schemes(request)

    ws_url = f"/fastapi/ws?cid={pod_name}&sid={uuid.uuid4().hex}"
    
    vnc_url = f"{http_scheme}://{host_only}:{host_novnc_port}/vnc.html?autoconnect=true&encrypt=0&resize=remote&password=jaewoo"

    return CreateContainerResponse(
        id=pod_name, name=pod_name, image=image, owner=user.username, limited_by_quota=(user.role == ROLE_FREE),
        role=user.role, projectName=body.projectName, vnc_url=vnc_url, ws_url=ws_url, port=host_novnc_port
    )

@app.get("/containers/my")
async def list_my_containers(user: AuthUser = Depends(get_current_user), api_client: httpx.AsyncClient = Depends(get_api_client)):
    try:
        resp = await api_client.get("/internal/api/containers")
        return resp.json()
    except Exception as e:
        raise HTTPException(503, detail=f"목록 조회 실패: {e}")

@app.get("/containers/{container_id}/urls", response_model=ContainerUrlsResponse)
async def get_container_urls(container_id: str, request: Request, user: AuthUser = Depends(get_current_user)):
    host_port = get_vnc_node_port(container_id)
    if not host_port: raise HTTPException(409, detail="NodePort not found")
    _, http_scheme, _, host_only = _build_netloc_and_schemes(request)
    ws_url = f"/fastapi/ws?cid={container_id}&sid={uuid.uuid4().hex}"
    vnc_url = f"{http_scheme}://{host_only}:{host_port}/vnc.html?autoconnect=true&password=jaewoo"
    return ContainerUrlsResponse(cid=container_id, ws_url=ws_url, vnc_url=vnc_url)

# == WebSocket 터미널 == #
@app.websocket("/ws")
async def websocket_terminal(websocket: WebSocket, cid: str = Query(..., alias="cid"), client_sid: Optional[str] = Query(None, alias="sid")):
    print(f"accept 전 websocket: {websocket}, cid : {cid}, client_sid : {client_sid}")
    await websocket.accept()
    print(f"accept 후")

    v1 = client.CoreV1Api()
    
    try:
        print(f"try 들어감")

        # tty=True일 때 /bin/bash가 가장 안정적입니다.
        resp = stream(v1.connect_get_namespaced_pod_exec, name=cid, namespace="webide-net",
                      command=["/bin/bash"], stderr=True, stdin=True, stdout=True, tty=True, _preload_content=False)

        if not client_sid: client_sid = uuid.uuid4().hex
        key = (cid, client_sid)
        sessions[key] = resp 
        
        await websocket.send_json({"sid": client_sid})
        # 연결 직후 엔터 키를 강제로 입력하여 프롬프트를 깨웁니다.
        resp.write_stdin("\n")

        async def read_from_pod():
            try:
                while resp.is_open():
                    # 🚀 더 안정적인 데이터 읽기 방식
                    if resp.peek_stdout():
                        data = resp.read_stdout()
                        if data: await websocket.send_text(data)
                    await asyncio.sleep(0.01) # CPU 부하 방지
            except Exception as e:
                print(f"📡 [Reader Error] {e}")

        async def write_to_pod():
            try:
                while resp.is_open():
                    msg = await websocket.receive_text()
                    resp.write_stdin(msg)
            except WebSocketDisconnect:
                pass
            except Exception as e:
                print(f"📡 [Writer Error] {e}")

        await asyncio.gather(read_from_pod(), write_to_pod())
    except Exception as e:
        print(f"❌ [WS MAIN ERROR] {e}")
    finally:
        if 'key' in locals(): sessions.pop(key, None)
        if 'resp' in locals(): resp.close()

# == 파일 시스템 조작 == #
@app.get("/files/{container_id}", response_model=FileStructureResponse)
def get_files(container_id: str):
    try:
        # 1. 파일 목록 (find)
        raw_output = k8s_exec_run(container_id, ["bash", "-c", f"find {WORKSPACE} -print0"])
        if not raw_output:
            return FileStructureResponse(tree={"id":"root","type":"folder","children":[]}, fileMap={"root":{"name":"","type":"folder"}})
        
        paths = [p for p in raw_output.split('\0') if p]
        file_paths_blob = k8s_exec_run(container_id, ["bash", "-c", f"find {WORKSPACE} -type f -print0"])
        file_paths_set = set(file_paths_blob.split('\0'))

        # 2. 파일 내용 (cat)
        contents = {}
        valid_paths = [p for p in file_paths_set if p]
        if valid_paths:
            delimiter = "---FILE-DELIMITER---"
            # f-string 밖에서 경로 문자열을 먼저 만듭니다.
            paths_quoted = " ".join([f'"{p}"' for p in valid_paths])
            cmd = f"for f in {paths_quoted}; do cat \"$f\"; echo \"{delimiter}\"; done"
            content_blob = k8s_exec_run(container_id, ["bash", "-c", cmd])
            split_contents = content_blob.split(delimiter)
            for i, path in enumerate(valid_paths):
                if i < len(split_contents): contents[path] = split_contents[i].strip()

        # 3. 트리 생성
        file_map, nodes = {"root": {"name": "", "type": "folder"}}, {"root": {"id": "root", "type": "folder", "children": []}}
        for path_str in sorted(paths):
            p = Path(path_str)
            if p == Path(WORKSPACE): continue
            node_id, name = str(uuid.uuid4()), p.name
            parent_path = str(p.parent)
            parent_id = "root"
            for nid, n in nodes.items():
                if n.get("path") == parent_path: parent_id = nid; break
            
            is_file = path_str in file_paths_set
            new_node = {"id": node_id, "type": "file" if is_file else "folder", "path": path_str}
            if not is_file: new_node["children"] = []
            nodes[node_id] = new_node
            nodes[parent_id]["children"].append(new_node)
            file_map[node_id] = {"name": name, "type": "file" if is_file else "folder", "path": path_str, "content": contents.get(path_str)}

        for node in nodes.values(): node.pop("path", None)
        return FileStructureResponse(tree=nodes["root"], fileMap=file_map)
    except Exception as e: raise HTTPException(500, detail=str(e))

@app.post("/run")
def run_code(req: CodeRequest):
    try:
        k8s_exec_run(req.container_id, ["mkdir", "-p", WORKSPACE])
        exec_path = create_file(req.container_id, req.tree, req.fileMap, req.run_code, base_path=WORKSPACE)
        k8s_exec_run(req.container_id, ["bash", "-c", f"pkill -f '{WORKSPACE}' || true"])
        
        # PTY 세션에 실행 명령 주입
        key = (req.container_id, req.session_id)
        if key in sessions:
            sessions[key].write_stdin(f"{venv_path}/bin/python '{exec_path}'\n")

        for _ in range(5):
            check = k8s_exec_run(req.container_id, ["bash", "-c", "DISPLAY=:1 xwininfo -root -tree | grep -E '\"[^ ]+\"' && echo yes || echo no"])
            if "yes" in check: return {"mode": "gui"}
            time.sleep(0.2)
        return {"mode": "cli"}
    except Exception as e: raise HTTPException(500, detail=str(e))

@app.post("/save")
def save_code(req: CodeSaveRequest):
    try:
        k8s_exec_run(req.container_id, ["mkdir", "-p", WORKSPACE])
        create_file(req.container_id, req.tree, req.fileMap, req.run_code, base_path=WORKSPACE)
        return {"message": "Saved"}
    except Exception as e: raise HTTPException(500, detail=str(e))

@app.patch("/files/{container_id}")
def rename_file(container_id: str, req: RenameFileRequest):
    old_path_obj = Path(req.old_path)
    new_path = (old_path_obj.parent / req.new_name).as_posix()
    result = k8s_exec_run(container_id, ["mv", req.old_path, new_path])
    return {"message": "Rename successful", "new_path": new_path}

@app.delete("/files/{container_id}")
def delete_file(container_id: str, req: FileDeleteRequest):
    k8s_exec_run(container_id, ["rm", "-rf", req.file_path])
    return {"message": "Deleted"}

@app.delete("/containers/{container_id}", status_code=204)
async def delete_container(container_id: str, user: AuthUser = Depends(get_current_user), api_client: httpx.AsyncClient = Depends(get_api_client)):
    await api_client.delete(f"/internal/api/containers/{container_id}/owner/{user.username}")
    delete_vnc_pod_and_service(container_id)

@app.patch("/containers/{container_id}")
async def update_project_name(container_id: str, req: RenameProjectRequest, user: AuthUser = Depends(get_current_user), api_client: httpx.AsyncClient = Depends(get_api_client)):
    await api_client.patch(f"/internal/api/containers/{container_id}/owner/{user.username}", json={"projectName": req.project_name})
    return {"message": "Updated"}


# import uuid, socket, time, docker, httpx, asyncio

# from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends, status, Query

# from fastapi.responses import FileResponse, JSONResponse
# from fastapi.staticfiles import StaticFiles
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from starlette.websockets import WebSocketState
# from uuid import uuid4
# from typing import AsyncGenerator, Dict, Tuple, List, Optional
# from security.security import get_current_user, AuthUser, _extract_bearer_token
# from urllib.parse import urlsplit
# from config import ROLE_ADMIN, ROLE_MEMBER, ROLE_FREE, FREE_MAX_CONTAINERS, DOCKER_NETWORK, VNC_IMAGE, CONTAINER_ENV_DEFAULT, INTERNAL_NOVNC_PORT, WORKSPACE, ALLOWED_NOVNC_PORTS
# from docker_client import get_docker
# # --- 모델 관련 import 시작 ---
# from models.CodeRequest import CodeRequest
# from models.CreateContainerRequest import CreateContainerRequest
# from models.CreateContainerResponse import CreateContainerResponse
# from models.ContainerUrlsResponse import ContainerUrlsResponse
# from models.FileStructureResponse import FileStructureResponse
# from models.CodeSaveRequest import CodeSaveRequest
# from models.FileDeleteRequest import FileDeleteRequest 
# from models.RenameFileRequest import RenameFileRequest
# from models.RenameProjectRequest import RenameProjectRequest

# from k8s_vnc import create_vnc_pod_and_service, delete_vnc_pod_and_service, get_vnc_node_port

# # --- 모델 관련 import 끝 ---
# from utils.util import get_api_client, _get_sendable_socket, _build_netloc_and_schemes, is_unlimited, create_file
# import json
# from pathlib import Path

# app = FastAPI()

# # CORS 설정
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # == 공통 설정 == #
# # Docker 클라이언트 & 컨테이너 이름
# docker_client = get_docker()


# venv_path = "/tmp/user_venv" # 가상환경 주소

# # (cid, sid) -> PTY
# sessions: Dict[Tuple[str, str], socket.socket] = {}
# UNLIMITED_ROLES = {ROLE_MEMBER, ROLE_ADMIN}

# # 짧은 도커 컨테이너 ID를 실제 전체 컨테이너 ID로 변환
# def _resolve_container_id(container_id: str) -> str:
#     # 1) 정확 조회
#     try:
#         return docker_client.containers.get(container_id).id
#     except docker.errors.NotFound:
#         pass

#     # 2) prefix 매칭
#     matches = [
#         c.id for c in docker_client.containers.list(all=True)
#         if c.id.startswith(container_id)
#     ]

#     if len(matches) == 1:
#         return matches[0]
#     elif len(matches) == 0:
#         raise docker.errors.NotFound(f"No container matches id/prefix '{container_id}'")
#     else:
#         # 모호한 접두어
#         raise RuntimeError(f"Ambiguous id prefix '{container_id}' matches {len(matches)} containers")

# @app.get("/me")
# async def me(user: AuthUser = Depends(get_current_user)):
#     return {"username": user.username, "role": user.role}

# @app.get("/test")
# def test():
#     return "test"

# # == 컨테이너 생성 == #
# create_container_lock = asyncio.Lock()

# # 이름으로 컨테이너 지우기
# def _rm_container_by_name(name: str):
#     try:
#         for c in docker_client.containers.list(all=True, filters={"name": f"^{name}$"}):
#             try:
#                 c.remove(force=True)
#             except Exception:
#                 pass
#     except Exception:
#         pass


# @app.post("/containers", response_model=CreateContainerResponse, status_code=201)
# async def create_container(
#     body: CreateContainerRequest,
#     request: Request,
#     user: AuthUser = Depends(get_current_user),
#     api_client: httpx.AsyncClient = Depends(get_api_client),
# ):
#     # 1) FREE 사용자 제한
#     if not is_unlimited(UNLIMITED_ROLES, user.role):
#         try:
#             resp = await api_client.get(f"internal/api/containers/count/{user.username}")
#             resp.raise_for_status()
#             if resp.json().get("count", 0) >= FREE_MAX_CONTAINERS:
#                 raise HTTPException(429, "최대 생성 개수를 초과했습니다.")
#         except httpx.RequestError as e:
#             raise HTTPException(503, detail=f"데이터 서버 연결 실패: {e}")

#     image = body.image or VNC_IMAGE
#     image = "jaewoo6257/vnc:1.0.0"

#     env = dict(CONTAINER_ENV_DEFAULT)
#     if body.env:
#         env.update(body.env)

#     pod_name = None
#     host_novnc_port = None
#     last_err = None

#     # 2) 락 안에서 NodePort 선정 + Pod/Service 생성
#     async with create_container_lock:
#         for p in ALLOWED_NOVNC_PORTS:
#             try:
#                 res = create_vnc_pod_and_service(
#                     username=user.username,
#                     image=image,
#                     env=env,
#                     internal_vnc_port=INTERNAL_NOVNC_PORT,
#                     node_port=p,
#                     project_name=body.projectName,
#                 )
#                 pod_name = res["pod_name"]
#                 host_novnc_port = res["node_port"]
#                 break
#             except Exception as e:
#                 # NodePort 이미 사용 중이거나 기타 오류 → 다음 포트 시도
#                 last_err = e
#                 continue

#     if pod_name is None or host_novnc_port is None:
#         raise HTTPException(503, detail=f"포트 충돌로 VNC Pod 생성 실패 (last: {last_err})")

#     # 3) DB 등록 (실패 시 K8s 자원 정리)
#     try:
#         payload = {
#             "containerId": pod_name,             # 이제부터 containerId = pod_name
#             "containerName": pod_name,
#             "ownerUsername": user.username,
#             "imageName": image,
#             "status": "Running",                 # 나중에 K8s 상태 조회로 바꿀 수도 있음
#             "projectName": body.projectName,
#             "port": host_novnc_port,
#         }
#         resp = await api_client.post("/internal/api/containers", json=payload)
#         resp.raise_for_status()
#     except httpx.RequestError as e:
#         # DB 등록 실패 시 Pod/Service 삭제
#         delete_vnc_pod_and_service(pod_name)
#         raise HTTPException(500, detail=f"컨테이너 정보 등록 실패: {e}") from e

#     # 4) URL 생성
#     netloc, http_scheme, ws_scheme, host_only = _build_netloc_and_schemes(request)
#     sid = uuid.uuid4().hex

#     # ws_url = f"{ws_scheme}://{netloc}/fastapi/ws?cid={pod_name}&sid={sid}"
#     ws_url = f"/fastapi/ws?cid={pod_name}&sid={sid}"
#     vnc_url = (
#         f"{http_scheme}://{host_only}:{host_novnc_port}"
#         "/vnc.html?autoconnect=true&encrypt=0&resize=remote&password=jaewoo"
#     )

#     # 5) 응답
#     return CreateContainerResponse(
#         id=pod_name,
#         name=pod_name,
#         image=image,
#         owner=user.username,
#         role=user.role,
#         limited_by_quota=(user.role == ROLE_FREE),
#         projectName=body.projectName,
#         vnc_url=vnc_url,
#         ws_url=ws_url,
#         port=host_novnc_port,
#     )



# # == 내 컨테이너 목록 조회 == #
# @app.get("/containers/my")
# async def list_my_containers(
#     user: AuthUser = Depends(get_current_user),
#     api_client: httpx.AsyncClient = Depends(get_api_client)
# ):
#     try:
#         resp = await api_client.get("/internal/api/containers")
#         resp.raise_for_status()
#         return resp.json()
#     except httpx.RequestError as e:
#         raise HTTPException(503, detail=f"데이터 서버에서 목록 조회 실패: {e}")


# @app.get("/containers/{container_id}/urls", response_model=ContainerUrlsResponse)
# async def get_container_urls(
#     container_id: str,
#     request: Request,
#     user: AuthUser = Depends(get_current_user),
# ):
#     # container_id = pod_name 으로 가정
#     host_port = get_vnc_node_port(container_id)

#     if not host_port:
#         raise HTTPException(status_code=409, detail="noVNC NodePort not found for this container")

#     netloc, http_scheme, ws_scheme, host_only = _build_netloc_and_schemes(request)

#     sid = uuid.uuid4().hex
#     # ws_url = f"{ws_scheme}://{netloc}/fastapi/ws?cid={container_id}&sid={sid}"
#     ws_url = f"/fastapi/ws?cid={container_id}&sid={sid}"
#     vnc_url = (
#         f"{http_scheme}://{host_only}:{host_port}"
#         "/vnc.html?autoconnect=true&encrypt=0&resize=remote&password=jaewoo"
#     )
#     return ContainerUrlsResponse(cid=container_id, ws_url=ws_url, vnc_url=vnc_url)



# # (cid, sid) ─> (우리 앱의 세션 키) -> pty_socket ─> (Docker 내부)─> exec_id, TTY

# @app.websocket("/ws")
# async def websocket_terminal(
#     websocket: WebSocket,
#     cid: str = Query(..., alias="cid"),
#     client_sid: Optional[str] = Query(None, alias="sid")
# ):
#     print(f"🔥 [WS START] cid: {cid}, sid: {client_sid}")
#     await websocket.accept()
    
#     key = None # 나중에 finally에서 세션을 지우기 위함
#     try:
#         # 1. 컨테이너 객체 가져오기 (K8s 대응)
#         try:
#             # 먼저 정규화 시도
#             full_id = _resolve_container_id(cid)
#             container = docker_client.containers.get(full_id)
#         except Exception as e:
#             print(f"⚠️ [WS] _resolve 실패, cid 직접 시도: {e}")
#             try:
#                 # 정규화 실패 시 cid(Pod Name)를 직접 넣어 조회
#                 container = docker_client.containers.get(cid)
#                 full_id = cid
#             except Exception as e2:
#                 print(f"❌ [WS] 컨테이너를 찾을 수 없음: {e2}")
#                 await websocket.send_text("🔴 컨테이너를 찾을 수 없습니다.")
#                 await websocket.close()
#                 return

#         # 2. SID 설정
#         if not client_sid:
#             client_sid = uuid.uuid4().hex
        
#         key = (full_id, client_sid)
#         print(f"🔑 [WS] Session Key: {key}")

#         if key in sessions:
#             print(f"⚠️ [WS] 중복 세션 발생")
#             await websocket.close(code=4409)
#             return

#         await websocket.send_json({"sid": client_sid})

#         # 3. venv 보장 (무거운 작업)
#         # 이미지가 커서 여기서 시간이 오래 걸리면 타임아웃 날 수 있음
#         try:
#             print("📦 [WS] venv 체크 중...")
#             ensure_venv = f"if [ ! -x '{venv_path}/bin/python' ]; then python3 -m venv '{venv_path}'; fi"
#             container.exec_run(["bash", "-c", ensure_venv])
#         except Exception as e:
#             print(f"⚠️ [WS] venv 체크 실패(무시가능): {e}")

#         # 4. TTY 세션 실행
#         print("⌨️ [WS] Bash 세션 생성 중...")
#         exec_create_resp = docker_client.api.exec_create(
#             container.id,
#             cmd=[
#                 "bash", "-lc",
#                 f"source {venv_path}/bin/activate >/dev/null 2>&1 || true; "
#                 f"export PS1='webide:\\w$ '; exec bash --noprofile --norc -i"
#             ],
#             tty=True,
#             stdin=True,
#         )
#         exec_id = exec_create_resp["Id"]

#         sock = docker_client.api.exec_start(exec_id, tty=True, socket=True)
#         pty = _get_sendable_socket(sock)
#         sessions[key] = pty 

#         loop = asyncio.get_event_loop()

#         async def reader():
#             try:
#                 while True:
#                     data = await loop.run_in_executor(None, pty.recv, 1024)
#                     if not data: break
#                     await websocket.send_text(data.decode(errors="ignore"))
#             except Exception as e:
#                 print(f"📡 [Reader Error] {e}")

#         async def writer():
#             try:
#                 while True:
#                     msg = await websocket.receive_text()
#                     await loop.run_in_executor(None, pty.send, msg.encode())
#             except WebSocketDisconnect:
#                 print("🔌 [WS] 클라이언트 연결 종료")
#             except Exception as e:
#                 print(f"📡 [Writer Error] {e}")

#         await asyncio.gather(reader(), writer())

#     except Exception as e:
#         print(f"❌ [WS MAIN ERROR] {e}")
#     finally:
#         if key:
#             sessions.pop(key, None)
#         print(f"🚿 [WS CLOSED] cid: {cid}")

# # == 컨테이너 파일 구조 읽기 == #
# @app.get("/files/{container_id}", response_model=FileStructureResponse)
# def get_files(container_id: str):
#     print("\n--- Debugging get_files ---")
#     try:
#         full_id = _resolve_container_id(container_id)
#         container = docker_client.containers.get(full_id)
#     except docker.errors.NotFound:
#         raise HTTPException(status_code=404, detail="Container not found")

#     # 컨테이너에서 파일 및 폴더 목록 가져오기 
#     exit_code, raw_output = container.exec_run(f"find {WORKSPACE} -print0")
#     if exit_code != 0:
#         # WORKSPACE가 없는 초기 상태일 수 있으므로 빈 구조 반환
#         return FileStructureResponse(
#             tree={"id": "root", "type": "folder", "children": []},
#             fileMap={"root": {"name": "", "type": "folder"}}
#         )

#     paths = [p for p in raw_output.decode().split('\0') if p]

#     # 컨테이너에서 파일 목록 가져오기 
#     _, file_paths_blob = container.exec_run(f"find {WORKSPACE} -type f -print0")
#     file_paths = file_paths_blob.decode().split('\0')
#     file_paths_set = set(file_paths) # 빠른 조회를 위해 set으로 변환

#     # 파일 내용 한 번에 읽어오기 
#     contents = {}
#     valid_file_paths = [p for p in file_paths if p] # 공백 제거

#     if valid_file_paths:

#         delimiter = "---FILE-CONTENT-DELIMITER---"

#         # 파일 내용 출력 명령어 생성 및 실행
#         paths_str = " ".join([f"'{p}'" for p in valid_file_paths])
#         cmd = f"bash -c 'for f in {paths_str}; do cat \"$f\"; echo \"{delimiter}\"; done'"
#         _, content_blob = container.exec_run(cmd)
        
#         split_contents = content_blob.decode().split(delimiter)
#         # 마지막 구분자 때문에 생기는 빈 항목 제거
#         if len(split_contents) > len(valid_file_paths):
#             split_contents.pop()

#         for i, path in enumerate(valid_file_paths):
#             contents[path] = split_contents[i]


#     # tree와 fileMap 구조로 재구성
#     file_map = {"root": {"name": "", "type": "folder"}}
#     nodes = {"root": {"id": "root", "type": "folder", "children": []}}
    
#     # 경로를 정렬하여 부모가 항상 자식보다 먼저 오도록 함
#     print("[DEBUG] Starting tree construction...")
#     for path_str in sorted(paths):
#         p = Path(path_str)
#         if p == Path(WORKSPACE): continue # 작업공간 루트는 건너뜀

#         id = str(uuid.uuid4())
#         name = p.name
#         parent_path_str = str(p.parent)
        
#         parent_id = "root"
#         if parent_path_str != WORKSPACE:
#             # 부모 노드의 id 찾기
#             for node_id, node in nodes.items():
#                 if node.get("path") == parent_path_str:
#                     print(f"[DEBUG] SKIPPING: Could not find parent for {path_str}")
#                     parent_id = node_id
#                     break

#         # 파일 여부를 file_paths_set에 있는지 확인하여 정확하게 판단
#         is_file = path_str in file_paths_set
#         node_type = "file" if is_file else "folder"
        
#         new_node = {"id": id, "type": node_type, "path": path_str}
#         if not is_file:
#             new_node["children"] = []

#         # 부모가 없는 경우(예: 잘못된 경로) 건너뛰기
#         if parent_id not in nodes: 
#             print(f"[DEBUG] SKIPPING: parent_id '{parent_id}' not in node for {path_str}")
#             continue 

#         nodes[id] = new_node
#         # 부모 노드에 children이 없으면 생성
#         if "children" not in nodes[parent_id]:
#              nodes[parent_id]["children"] = []
#         nodes[parent_id]["children"].append(new_node)
        
#         file_map[id] = {
#             "name": name,
#             "type": node_type,
#             "path": path_str,
#             "content": contents.get(path_str, None) if is_file else None
#         }

#     # 'path' 임시 키 제거
#     for node in nodes.values():
#         node.pop("path", None)
#     print("--- End of get_files debug ---\n")
#     return FileStructureResponse(tree=nodes["root"], fileMap=file_map)

# # == 코드 실행 == #
# @app.post("/run")
# def run_code(req: CodeRequest):

#     # 컨테이너 ID 풀ID로 정규화
#     try:
#         container = docker_client.containers.get(req.container_id)
#     except docker.errors.NotFound:
#         try:
#             full_id = _resolve_container_id(req.container_id)
#             container = docker_client.containers.get(full_id)
#         except docker.errors.NotFound:
#             return JSONResponse(status_code=404, content={"error": "Container not found"})

#     full_id = container.id
#     key = (full_id, req.session_id)
#     pty = sessions.get(key) # 세션이용해서 PTY 연결하기

#     if not pty:
#         raise HTTPException(400, detail="PTY 세션이 준비되지 않았습니다. 먼저 /ws 로 연결하세요.")

#     try:
#         # WORKSPACE 폴더가 없는 경우에만 생성
#         container.exec_run(["mkdir", "-p", WORKSPACE])

#         # 파일 생성
#         exec_path = create_file(container, req.tree, req.fileMap, req.run_code, base_path=WORKSPACE)
#         if not exec_path:
#             raise HTTPException(400, "실행 파일(run_code)을 찾지 못했습니다.")
    
#         # 이전 실행 종료
#         container.exec_run(["bash", "-lc", f"pkill -f '{WORKSPACE}' || true"])

#         # venv 파이썬으로 실행 (명시적으로)
#         pty.send(f"{venv_path}/bin/python '{exec_path}'\n".encode()) # 실행할 파일의 전체 경로를 PTY(가상 터미널) 세션으로 전송

#         # 최대 2초 (0.2초 * 10번) 동안 GUI 실행 여부를 확인
#         for _ in range(5):
#             check = container.exec_run( 
#                 cmd=["bash", "-c", "DISPLAY=:1 xwininfo -root -tree | grep -E '\"[^ ]+\"' && echo yes || echo no"]
#             )
#             # 루트 트리에 GUI 창이 존재하는지 체크
#             if b"yes" in check.output:
#                 return {"mode": "gui"}
#             time.sleep(0.2)

#         # CLI 모드 결과 
#         return {"mode": "cli"}
#     except Exception as e:
#         raise HTTPException(500, detail=f"PTY 전송 실패: {e}")

# # 코드 저장하기
# @app.post("/save")
# def save_code(req: CodeSaveRequest):

#     # 컨테이너 ID 풀ID로 정규화
#     try:
#         container = docker_client.containers.get(req.container_id)
#     except docker.errors.NotFound:
#         try:
#             full_id = _resolve_container_id(req.container_id)
#             container = docker_client.containers.get(full_id)
#         except docker.errors.NotFound:
#             return JSONResponse(status_code=404, content={"error": "Container not found"})

#     try:
#         # WORKSPACE 폴더가 없는 경우에만 생성
#         container.exec_run(["mkdir", "-p", WORKSPACE])

#         # 파일 생성
#         exec_path = create_file(container, req.tree, req.fileMap, req.run_code, base_path=WORKSPACE)
#     except Exception as e:
#         raise HTTPException(500, detail=f"PTY 전송 실패: {e}")

# # == 파일명 수정 == #
# @app.patch("/files/{container_id}")
# def rename_file(container_id: str, req: RenameFileRequest):
#     print("\n--- Debugging rename_file ---")
#     try:
#         full_id = _resolve_container_id(container_id)
#         container = docker_client.containers.get(full_id)
#     except docker.errors.NotFound:
#         raise HTTPException(status_code=404, detail="Container not found")   
   
#     # 경로 유효성 검사
#     if not req.old_path.startswith(WORKSPACE) or "/" in req.new_name:        
#         raise HTTPException(status_code=400, detail="Invalid old path or new name.")
   
#     # 새로운 경로 생성
#     old_path_obj = Path(req.old_path)
#     new_path_obj = old_path_obj.parent / req.new_name    
    
#     # new_path를 POSIX (Linux) 형식의 문자열로 변환
#     new_path_posix = new_path_obj.as_posix()
    
#     # 컨테이너 내에서 mv 명령 실행
#     exit_code, output = container.exec_run(f"mv '{req.old_path}' '{new_path_posix}'")

#     if exit_code != 0:
#         error_message = output.decode().strip()
#         raise HTTPException(status_code=500, detail=f"Failed to rename: {error_message}")
    
#     # 성공 시, 새로운 경로를 포함하여 응답
#     return {"message": "Rename successful", "new_path": new_path_posix} 

# # == 파일 삭제 == #
# @app.delete("/files/{container_id}")
# def delete_file(container_id: str, req: FileDeleteRequest):
#     try:
#         full_id = _resolve_container_id(container_id)
#         container = docker_client.containers.get(full_id)
#     except docker.errors.NotFound:
#         raise HTTPException(status_code=404, detail="Container not found")

#     # 파일 삭제 명령 실행
#     exit_code, output = container.exec_run(f"rm -f '{req.file_path}'")

#     if exit_code != 0:
#         error_message = output.decode().strip()
#         raise HTTPException(status_code=500, detail=f"파일 삭제 실패: {output.decode()}")

#     return {"message": f"파일 '{req.file_path}'이(가) 성공적으로 삭제되었습니다."}

# @app.delete("/containers/{container_id}", status_code=status.HTTP_204_NO_CONTENT)
# async def delete_container(
#     container_id: str,
#     user: AuthUser = Depends(get_current_user),
#     api_client: httpx.AsyncClient = Depends(get_api_client),
# ):
#     full_id = container_id  # 이제 containerId = pod_name 으로 사용

#     # 1) DB에서 삭제
#     try:
#         delete_resp = await api_client.delete(f"/internal/api/containers/{full_id}/owner/{user.username}")
#         if 400 <= delete_resp.status_code < 500:
#             raise HTTPException(status_code=delete_resp.status_code, detail=f"DB 업데이트 실패: {delete_resp.text}")
#         delete_resp.raise_for_status()
#     except httpx.RequestError as e:
#         raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"DB 접근 실패: {e}")

#     # 2) K8s Pod/Service 삭제
#     try:
#         delete_vnc_pod_and_service(full_id)
#     except Exception as e:
#         print(f"K8s VNC Pod/Service 삭제 실패 {full_id}: {e}")

#     return


# # == 컨테이너 수정 == #
# @app.patch("/containers/{container_id}")
# async def update_project_name(
#     container_id: str,
#     req: RenameProjectRequest,
#     user: AuthUser = Depends(get_current_user),
#     api_client: httpx.AsyncClient = Depends(get_api_client),
# ):
#     try:
#         full_id = _resolve_container_id(container_id)
#     except (docker.errors.NotFound, RuntimeError):
#         full_id = container_id
                                                                                                                                                                                                                                             
#     try:
#         update_resp = await api_client.patch(
#             f"/internal/api/containers/{full_id}/owner/{user.username}",
#             json={"projectName": req.project_name}
#         )
#         if 400 <= update_resp.status_code < 500:
#             raise HTTPException(status_code=update_resp.status_code, detail=f"DB 업데이트 실패: {update_resp.text}")
#         update_resp.raise_for_status()
#     except httpx.RequestError as e:
#         raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"DB 접속 실패 {e}")
                                                                                                                                                                                                                                             
#     return {"message": "성공적으로 컨테이너명 업데이트"}
