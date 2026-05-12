from doghouse.common.config import DoghouseConfig, PathsConfig
from doghouse.evidence.daily import generate_daily_evidence
from doghouse.qa.gate import run_qa_gate


def test_qa_gate_can_fail_without_services(tmp_path, monkeypatch):
    cfg = DoghouseConfig(paths=PathsConfig(state_dir=str(tmp_path / "state"), incident_dir=str(tmp_path / "inc"), log_dir=str(tmp_path / "log"), checkpoint_dir=str(tmp_path / "chk")))
    monkeypatch.setattr("doghouse.qa.gate.load_services", lambda *_: [])
    monkeypatch.setattr("doghouse.qa.gate.run_audit", lambda *a, **k: {"status": "ok", "sections": {"scheduler_freshness": {"status": "ok"}, "paths": {"status": "ok"}, "executor_policy": {"status": "ok"}, "devtask_state": {"status": "ok"}}})
    monkeypatch.setattr("doghouse.qa.gate.shadow_once", lambda *a, **k: {"status": "ok"})
    monkeypatch.setattr("doghouse.qa.gate.generate_soak_report", lambda *a, **k: {"restart_actions": [], "incidents": {"count": 0}})
    report = run_qa_gate(cfg, threshold=10, persist=True)
    assert report["status"] == "fail"
    assert (tmp_path / "state" / "qa" / "latest-qa-gate.json").exists()


def test_daily_evidence_writes_json_and_markdown(tmp_path, monkeypatch):
    cfg = DoghouseConfig(paths=PathsConfig(state_dir=str(tmp_path / "state"), incident_dir=str(tmp_path / "inc"), log_dir=str(tmp_path / "log"), checkpoint_dir=str(tmp_path / "chk")))
    monkeypatch.setattr("doghouse.evidence.daily.run_qa_gate", lambda *a, **k: {"status": "pass", "score": 10, "threshold": 8, "checks": []})
    monkeypatch.setattr("doghouse.evidence.daily.generate_soak_report", lambda *a, **k: {"status": "ok", "attention": [], "incidents": {"count": 0}, "restart_actions": [], "latest_states": {}})
    monkeypatch.setattr("doghouse.evidence.daily.run_audit", lambda *a, **k: {"status": "ok"})
    monkeypatch.setattr("doghouse.evidence.daily.shadow_once", lambda *a, **k: {"status": "ok"})
    report = generate_daily_evidence(cfg, persist=True)
    assert report["status"] == "pass"
    assert (tmp_path / "state" / "evidence" / "latest-daily-evidence.json").exists()
    assert (tmp_path / "state" / "evidence" / "latest-daily-evidence.md").exists()
