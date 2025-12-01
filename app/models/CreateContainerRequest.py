from pydantic import BaseModel
from typing import Dict, List, Optional


# 컨테이너 만들 때 사용되는 Request
class CreateContainerRequest(BaseModel):
    projectName: str
    image: Optional[str] = None
    cmd: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
