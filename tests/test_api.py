from fastapi.testclient import TestClient

from nodler.api import create_app


def client(tmp_path):
    return TestClient(create_app(tmp_path, start_worker=False))


def test_seeded_defaults(tmp_path):
    c = client(tmp_path)
    assert {a["id"] for a in c.get("/api/agents").json()} == {"coder", "reviewer"}
    wf = c.get("/api/workflows/default").json()["workflow"]
    assert wf["version"] == 1
    assert c.get("/api/state").json()["paused"] is True


def test_workflow_save_creates_version_and_rejects_invalid(tmp_path):
    c = client(tmp_path)
    wf = c.get("/api/workflows/default").json()["workflow"]
    wf["rules"][0]["limit"] = 5
    r = c.put("/api/workflows/default", json=wf)
    assert r.status_code == 200 and r.json()["workflow"]["version"] == 2
    assert [v["version"] for v in c.get("/api/workflows/default").json()["versions"]] == [2, 1]

    wf["transitions"][0]["outcome"] = "nonsense"
    r = c.put("/api/workflows/default", json=wf)
    assert r.status_code == 400


def test_validate_returns_outcomes(tmp_path):
    c = client(tmp_path)
    wf = c.get("/api/workflows/default").json()["workflow"]
    res = c.post("/api/workflows/validate", json=wf).json()
    assert res["errors"] == []
    assert res["outcomes"]["review"] == ["approved", "changes_requested", "check_failed"]


def test_agent_in_use_cannot_be_deleted(tmp_path):
    c = client(tmp_path)
    assert c.delete("/api/agents/coder").status_code == 400
    agent = {"id": "qa", "name": "QA", "system_prompt": "test it", "outcomes": [{"name": "pass"}]}
    assert c.put("/api/agents/qa", json=agent).status_code == 200
    assert c.delete("/api/agents/qa").status_code == 200
