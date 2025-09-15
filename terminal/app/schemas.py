# app/schemas.py
from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from datetime import datetime

class CreateContainerRequest(BaseModel):
    projectName: str = Field(description="Name of the project")
    image: Optional[str] = Field(default=None, description="Docker image to run")
    cmd: Optional[List[str]] = Field(default=None, description="Command/args to run")
    env: Optional[Dict[str, str]] = Field(default=None, description="Environment variables")
    # 필요한 추가 옵션들: ports, volumes 등

class CreateContainerResponse(BaseModel):
    id: str
    name: str
    image: str
    owner: str
    role: str
    limited_by_quota: bool
    projectName: str

class ContainerListResponse(BaseModel):
    projectName: str
    containerName: str
    language: str
    updatedAt: datetime
