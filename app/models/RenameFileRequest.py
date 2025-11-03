from pydantic import BaseModel

class RenameFileRequest(BaseModel):
    old_path: str
    new_name: str

