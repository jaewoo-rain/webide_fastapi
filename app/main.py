from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.v1.endpoints import run, ws

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

app.mount("/static", StaticFiles(directory="static", html=True), name="static")

@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse("static/index.html")

# 라우터 등록
app.include_router(run.router, prefix="")
app.websocket("/ws")(ws.websocket_terminal)
