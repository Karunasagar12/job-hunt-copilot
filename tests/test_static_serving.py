import paths


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert response.get_json()["version"]


def test_spa_fallback(client, tmp_path, monkeypatch):
    import api.app as app_mod

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    (dist / "app.js").write_text("js", encoding="utf-8")
    monkeypatch.setattr(app_mod, "DIST_DIR", dist)

    assert client.get("/settings").data == b"<html>spa</html>"
    assert client.get("/app.js").data == b"js"
    assert client.get("/api").status_code == 404
    assert client.get("/api/nope").status_code == 404


def test_spa_missing_dist(client, tmp_path, monkeypatch):
    import api.app as app_mod

    monkeypatch.setattr(app_mod, "DIST_DIR", tmp_path / "missing")
    response = client.get("/pipeline")
    assert response.status_code == 404
    assert response.get_json() == {"error": "dashboard not built"}
