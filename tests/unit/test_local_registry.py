"""The data/model handover must persist metadata without database access."""

import json
import socket

from src.models.registry import persist_registry_records


def test_registry_remains_local_with_database_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://invalid:invalid@localhost/unused")
    monkeypatch.setenv("DATABASE_URL", "postgresql://invalid:invalid@localhost/unused")

    def reject_connection(*args, **kwargs):
        raise AssertionError("Local registry must not connect to a database")

    monkeypatch.setattr(socket, "create_connection", reject_connection)
    row = {"model_id": "baseline1:v1", "model_version": "v1"}
    for _ in range(2):
        status = persist_registry_records(registry_dir=tmp_path, model_registry=[row])
    assert status["storage_backend"] == "local_json"
    assert status["status"] == "saved_local"
    assert status["table_counts"]["model_registry"] == 1
    assert json.loads((tmp_path / "model_registry.json").read_text(encoding="utf-8")) == [row]
