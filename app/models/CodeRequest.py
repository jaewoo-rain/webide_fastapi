from pydantic import BaseModel

class CodeRequest(BaseModel):
    code: str
    tree: dict
    fileMap: dict
    run_code: str
    session_id: str
    container_id: str