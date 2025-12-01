from pydantic import BaseModel
from typing import Dict, List, Optional

class FileNode(BaseModel):
    id: str
    type: str
    children: Optional[List['FileNode']] = None

class FileMapItem(BaseModel):
    name: str
    content: Optional[str] = None
    type: str
    path: Optional[str] = None
    
class FileStructureResponse(BaseModel):
    tree: FileNode
    fileMap: Dict[str, FileMapItem]