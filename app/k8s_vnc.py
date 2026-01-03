# k8s_vnc.py
from uuid import uuid4
from typing import Optional, Dict

from kubernetes import client, config
from kubernetes.client import (
    V1Pod,
    V1ObjectMeta,
    V1PodSpec,
    V1Container,
    V1Service,
    V1ServiceSpec,
    V1ServicePort,
    V1ContainerPort,
    V1EnvVar,
)

NAMESPACE = "webide-net" # 네임스페이스 이름 (k8s yaml과 동일)
VNC_APP_LABEL = "vnc-session" # VNC Pod/Service 공통 label


def get_core_v1():
    """
    클러스터 안에서는 in-cluster, 로컬 개발 시에는 kubeconfig 사용
    """
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    return client.CoreV1Api()


# 생성
def create_vnc_pod_and_service(
    username: str,
    image: str,
    env: Dict[str, str],
    internal_vnc_port: int,
    node_port: int,
    project_name: Optional[str] = None,
) -> Dict[str, str]:
    """
    1) VNC용 Pod 하나 생성
    2) 그 Pod를 노출하는 NodePort Service 하나 생성
    """
    core_v1 = get_core_v1()

    instance_id = uuid4().hex[:8]
    pod_name = f"{username}-{instance_id}"

    labels = {
        "app": VNC_APP_LABEL,
        "owner": username,
        "instance": instance_id,
    }
    if project_name:
        labels["project"] = project_name

    # 1) Pod 정의
    pod = V1Pod(
        metadata=V1ObjectMeta(
            name=pod_name,
            labels=labels,
        ),
        spec=V1PodSpec(
            containers=[
                V1Container(
                    name="vnc",
                    image=image,
                    ports=[V1ContainerPort(container_port=internal_vnc_port)],
                    env=[V1EnvVar(name=k, value=str(v)) for k, v in env.items()],
                )
            ]
        ),
    )

    pod = core_v1.create_namespaced_pod(namespace=NAMESPACE, body=pod)

    # 2) NodePort Service 정의
    service_name = f"{pod_name}-svc"
    service = V1Service(
        metadata=V1ObjectMeta(
            name=service_name,
            labels=labels,
        ),
        spec=V1ServiceSpec(
            type="NodePort",
            selector={"app": VNC_APP_LABEL, "instance": instance_id},
            ports=[
                V1ServicePort(
                    name="novnc",
                    port=internal_vnc_port,        # 클러스터 내부 포트
                    target_port=internal_vnc_port, # 포드 내부 포트
                    node_port=node_port,           # 외부에서 접속할 NodePort
                    protocol="TCP",
                )
            ],
        ),
    )

    service = core_v1.create_namespaced_service(namespace=NAMESPACE, body=service)

    return {
        "pod_name": pod.metadata.name,
        "service_name": service.metadata.name,
        "node_port": node_port,
    }

# 삭제
def delete_vnc_pod_and_service(container_id: str):
    """
    container_id = pod_name 이라고 가정하고
    1) Service (pod_name-svc) 삭제
    2) Pod 삭제
    """
    core_v1 = get_core_v1()

    pod_name = container_id
    svc_name = f"{pod_name}-svc"

    # Service 삭제
    try:
        core_v1.delete_namespaced_service(name=svc_name, namespace=NAMESPACE)
    except Exception:
        pass

    # Pod 삭제
    try:
        core_v1.delete_namespaced_pod(name=pod_name, namespace=NAMESPACE)
    except Exception:
        pass


def get_vnc_node_port(container_id: str) -> Optional[int]:
    """
    pod_name 기준으로 서비스(NodePort) 찾아서 실제 NodePort 번호 반환
    """
    core_v1 = get_core_v1()

    pod_name = container_id
    svc_name = f"{pod_name}-svc"

    try:
        svc = core_v1.read_namespaced_service(name=svc_name, namespace=NAMESPACE)
    except Exception:
        return None

    if not svc.spec or not svc.spec.ports:
        return None

    return svc.spec.ports[0].node_port
