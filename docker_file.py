from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uuid
import docker

app = FastAPI()
docker_client = docker.from_env()

class RunRequest(BaseModel):
    image: str = "docker-file"
    vnc_port: int = 10007
    novnc_port: int = 6080

@app.post("/create")
def run_container(req: RunRequest):
    # Generate a unique container name
    container_name = f"webide-vnc-{uuid.uuid4().hex[:8]}"
    try:
        container = docker_client.containers.run(
            req.image,
            detach=True,
            name=container_name,
            ports={
                f"{req.vnc_port}/tcp": req.vnc_port,
                f"{req.novnc_port}/tcp": req.novnc_port
            },
            restart_policy={"Name": "unless-stopped"}
        )
        return {"message": "Container started", "container_id": container.id, "name": container_name}
    except docker.errors.APIError as e:
        raise HTTPException(status_code=500, detail=f"Docker API error: {e.explanation}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status/{name}")
def get_status(name: str):
    try:
        container = docker_client.containers.get(name)
        return {"name": name, "status": container.status}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 실행 명령 예시
# uvicorn 파일명:app --reload --host 0.0.0.0 --port 5000
# 예: uvicorn main:app --reload --host 0.0.0.0 --port 5000
