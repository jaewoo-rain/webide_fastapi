import socket,  docker, httpx

from fastapi import Request

from security.security import  _extract_bearer_token
from urllib.parse import urlsplit
from config import SPRING_BOOT_API_URL
# == 유틸 == #

# 10000 ~ 10100포트 사이 비어있는 포트 반
# def find_free_port(start: int = 10000, end: int = 10100, host: str = "0.0.0.0") -> int:
#     """[start, end] 범위에서 사용 가능한 TCP 포트를 하나 찾아 반환.
#     주의: 반환 직후 다른 프로세스가 먼저 잡을 수 있는 레이스가 있습니다.
#     """
#     for port in range(start, end + 1):
#         s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#         try:
#             # SO_REUSEADDR는 일부 OS에서 TIME_WAIT 소켓 재바인드를 허용하므로 0(기본) 유지
#             s.bind((host, port))
#             return port
#         except OSError:
#             continue
#         finally:
#             s.close()
#     raise RuntimeError(f"No free port in range {start}-{end}")

# 스프링 연동
async def get_api_client(request: Request):
    token = _extract_bearer_token(request)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=SPRING_BOOT_API_URL, headers=headers, timeout=10.0) as client:
        yield client

# 소켓 적절한것으로 연동하기
def _get_sendable_socket(socklike) -> socket.socket:
    """
    docker SDK의 exec_start(..., socket=True)가 돌려주는 다양한 '소켓스러운' 객체에서
    실제 send/recv가 가능한 raw socket을 뽑아 반환한다.

    우선순위:
      1) 이미 socket.socket 이면 그대로 반환
      2) ._sock / .sock 속성으로 raw socket 보유 시 그걸 반환
      3) 마지막으로 객체 자체가 send/recv를 갖고 있으면 그대로 반환
      4) 어떤 경우에도 해당 안 되면 TypeError

    반환값은 블로킹 소켓일 수 있으니, 필요하면 setblocking(False) 등을 호출해 사용.
    """
    # 1) 진짜 소켓이면 그대로
    if isinstance(socklike, socket.socket):
        return socklike

    # 2) docker SDK가 감싸둔 경우: _sock 또는 sock 속성에 raw socket이 들어있음
    for attr in ("_sock", "sock"):
        raw = getattr(socklike, attr, None)
        if isinstance(raw, socket.socket):
            return raw

    # 3) 최소한 send/recv가 있으면 그대로 써도 됨 (일부 구현체가 이 케이스)
    if hasattr(socklike, "send") and hasattr(socklike, "recv"):
        # 타입 힌트를 위해 살짝 우겨넣기(런타임엔 정상 동작)
        return socklike  # type: ignore[return-value]

    # 4) 실패
    raise TypeError("send/recv 가능한 소켓을 찾지 못했습니다.")

# URL 분리하기
def _build_netloc_and_schemes(request: Request) -> tuple[str, str, str, str]:
    """
    http://localhost:8000 → netloc="localhost:8000", http_scheme="http", ws_scheme="ws",
    """
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


# role 이 member와 admin인지 확인하는 절차
def is_unlimited(UNLIMITED_ROLES, role: str) -> bool:
    return role in UNLIMITED_ROLES

# == 파일 생성 로직 == #
def create_file(container, tree, fileMap, run_code, base_path="/opt", path=None):
    if path is None:
        path = []
    result = None

    if tree["type"] == "folder":
        folder_name = fileMap[tree["id"]]["name"]
        path.append(folder_name)
        full_path = base_path + "/" + "/".join(path)
        container.exec_run(cmd=["mkdir", "-p", full_path])
        for node in tree.get("children", []):
            sub = create_file(container, node, fileMap, run_code, base_path, path)
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
