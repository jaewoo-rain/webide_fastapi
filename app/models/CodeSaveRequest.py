from pydantic import BaseModel

class CodeSaveRequest(BaseModel):
    code: str
    tree: dict
    fileMap: dict
    run_code: str
    container_id: str