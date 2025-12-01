from pydantic import BaseModel

class RenameProjectRequest(BaseModel):
    project_name: str
