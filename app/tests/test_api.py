import os

os.environ["SKIP_DB_INIT"] = "1"
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("COGNITO_POOL_ID", "us-east-1_test")
os.environ.setdefault("COGNITO_CLIENT_ID", "test")

from fastapi.testclient import TestClient  # noqa: E402

from exam_api.main import app  # noqa: E402

client = TestClient(app)


def test_health_check_for_the_load_balancer():
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_api_requires_sign_in():
    assert client.get("/api/exams").status_code == 401
    assert client.put("/api/attempts/1/answers", json={"answers": {"1": "x"}}).status_code == 401
    assert client.post("/api/assignments/1/upload-url",
                       json={"filename": "a.pdf", "content_type": "application/pdf", "size_bytes": 1}).status_code == 401
