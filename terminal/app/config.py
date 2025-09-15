# app/config.py
import os

FREE_MAX_CONTAINERS = int(os.getenv("FREE_MAX_CONTAINERS", "3"))
DOCKER_DEFAULT_IMAGE = os.getenv("DOCKER_DEFAULT_IMAGE", "python:3.12-slim")
DOCKER_NETWORK = os.getenv("DOCKER_NETWORK", None)  # 필요하면 bridge 이름
SPRING_BOOT_API_URL="http://localhost:8080/internal/api/"
# REDIS_URL = os.getenv("REDIS_URL", "")  # 예: redis://localhost:6379/0
