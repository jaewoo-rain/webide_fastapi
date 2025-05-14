from flask import Flask, render_template, request, jsonify
import subprocess
import uuid
import os
import tempfile

app = Flask(__name__)

DOCKER_NAME = "my-ubuntu"           # Docker 컨테이너 이름
DOCKER_DISPLAY = ":1"              # VNC DISPLAY 번호
TEMP_TURTLE_PATH = "temp_turtle.py"

@app.route('/')
def index():
    return render_template('index.html')


# 📌 1. 일반 코드 실행 (결과 텍스트 출력)
@app.route('/submit', methods=['POST'])
def run_code_locally():
    code = request.form.get('code')
    if not code:
        return jsonify({"error": "코드를 입력하세요"}), 400

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        filepath = f.name

    try:
        result = subprocess.run(
            ['python3', filepath],
            capture_output=True,
            text=True,
            timeout=5
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        output = "⏱️ 실행 시간이 초과되었습니다."
    finally:
        os.remove(filepath)

    return jsonify({'output': output})


# 📌 2. Docker에서 turtle 실행 (noVNC로 결과 확인)
@app.route('/run', methods=['POST'])
def run_turtle_in_docker():
    data = request.get_json()
    code = data.get("code")

    if not code:
        return jsonify({"error": "No code provided"}), 400

    # 1. 파일 저장
    local_path = os.path.join(os.getcwd(), TEMP_TURTLE_PATH)
    with open(local_path, "w") as f:
        f.write(code)

    # 2. Docker 컨테이너로 복사
    remote_path = f"/tmp/{TEMP_TURTLE_PATH}"
    subprocess.run(["docker", "cp", local_path, f"{DOCKER_NAME}:{remote_path}"])

    # 3. Docker 내부에서 DISPLAY=:2 로 실행
    subprocess.Popen([
        "docker", "exec", "-e", f"DISPLAY={DOCKER_DISPLAY}",
        DOCKER_NAME, "python3", remote_path
    ])

    return jsonify({"status": "running", "file": remote_path})


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)
