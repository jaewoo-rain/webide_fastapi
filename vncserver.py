from flask import Flask, request, jsonify
import subprocess
import uuid
import os

app = Flask(__name__)

# Docker 컨테이너 이름
DOCKER_NAME = "my-ubuntu"
DOCKER_DISPLAY = ":1"  # VNC 디스플레이 번호

@app.route('/run', methods=['POST'])
def run_code():
    code = request.json.get("code")
    if not code:
        return jsonify({"error": "No code provided"}), 400

    # 1. 임시 파일로 저장
    # filename = f"temp_{uuid.uuid4().hex}.py"
    filename = "temp_turtle.py"
    local_path = os.path.join(os.getcwd(), filename)
    with open(local_path, "w") as f:
        f.write(code)

    # 2. Docker로 복사
    remote_path = f"/tmp/{filename}"
    subprocess.run(["docker", "cp", local_path, f"{DOCKER_NAME}:{remote_path}"])

    # 3. Docker에서 실행 (백그라운드로)
    subprocess.Popen([
        "docker", "exec", "-e", f"DISPLAY={DOCKER_DISPLAY}",
        DOCKER_NAME, "python3", remote_path
    ])

    return jsonify({"status": "running", "file": remote_path})

@app.route('/')
def main():
    return 
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)
