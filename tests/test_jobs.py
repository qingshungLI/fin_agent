import pytest
from pydantic import ValidationError

from server_jobs import RunRequest


def test_job_request_rejects_arbitrary_paths_and_overallocation():
    with pytest.raises(ValidationError):
        RunRequest(data_root="/tmp/other")
    with pytest.raises(ValidationError):
        RunRequest(workers=100)
    with pytest.raises(ValidationError):
        RunRequest(provider="sh -c something")


def test_api_submission_validation_and_single_writer(monkeypatch):
    from fastapi.testclient import TestClient

    import server_jobs
    from engine.api import app
    client = TestClient(app)
    calls = []
    monkeypatch.setattr(server_jobs, "launch", lambda request: calls.append(request) or {"id": "job-test", "status": "QUEUED"})
    assert client.post("/api/jobs", json={}, headers={"origin": "https://external.example"}).status_code == 403
    assert client.post("/api/jobs", json={"workers": 100}).status_code == 422
    assert calls == []
    assert client.post("/api/jobs", json={"provider": "manual"}).status_code == 202
    assert len(calls) == 1
    def busy(request):
        raise RuntimeError("Another research writer is running")
    monkeypatch.setattr(server_jobs, "launch", busy)
    assert client.post("/api/jobs", json={}).status_code == 409
