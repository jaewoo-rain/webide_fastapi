from pydantic import BaseModel

class FileDeleteRequest(BaseModel):
    file_path: str
