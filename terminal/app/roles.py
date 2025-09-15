# app/roles.py
from typing import Final

ROLE_FREE: Final = "ROLE_FREE"
ROLE_MEMBER: Final = "ROLE_MEMBER"
ROLE_ADMIN: Final = "ROLE_ADMIN"

UNLIMITED_ROLES = {ROLE_MEMBER, ROLE_ADMIN}

def is_unlimited(role: str) -> bool:
    return role in UNLIMITED_ROLES
