from pydantic import BaseModel

# 컨테이너 접속 후 응답 Response -> 이걸 이용해서 새로고침 시 동일한 컨테이너로 접속 가능(다른 터미널 PTY)
class ContainerUrlsResponse(BaseModel):
    cid: str
    ws_url: str
    vnc_url: str