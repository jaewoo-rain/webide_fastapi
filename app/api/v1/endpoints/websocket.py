from fastapi import WebSocket, WebSocketDisconnect
import asyncio

from app.core import docker_client

async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()

    try:
        container = docker_client.client.containers.get(docker_client.CONTAINER_NAME)
    except Exception:
        await websocket.send_text("❌ 컨테이너가 없습니다.")
        await websocket.close()
        return

    exec_id = docker_client.client.api.exec_create(
        container.id, cmd="/bin/bash", tty=True, stdin=True
    )["Id"]

    sock = docker_client.client.api.exec_start(exec_id, tty=True, socket=True)
    docker_client.pty_socket = sock

    loop = asyncio.get_event_loop()

    async def read_from_container():
        try:
            while True:
                data = await loop.run_in_executor(None, sock._sock.recv, 1024)
                if not data:
                    break
                await websocket.send_text(data.decode(errors="ignore"))
        finally:
            await websocket.close()

    async def write_to_container():
        try:
            while True:
                msg = await websocket.receive_text()
                await loop.run_in_executor(None, sock._sock.send, msg.encode())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass
            docker_client.pty_socket = None
            await websocket.close()

    await asyncio.gather(read_from_container(), write_to_container())
