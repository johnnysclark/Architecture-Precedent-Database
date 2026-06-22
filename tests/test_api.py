"""End-to-end API smoke test through FastAPI's TestClient.

No network or API key required: alt generation degrades to a clear no_api_key
signal, which we assert. Exercises archive binding, intake, detail, alt edit,
search, and PIAF.
"""
from fastapi.testclient import TestClient
from PIL import Image

from server.main import app


def _png(path):
    Image.new("RGB", (64, 48), (90, 90, 90)).save(str(path))


def test_full_flow(tmp_path):
    _png(tmp_path / "a.png")
    client = TestClient(app)

    # Bind archive
    r = client.post("/api/settings/archive", json={"path": str(tmp_path)})
    assert r.status_code == 200 and r.json()["archiveSet"] is True

    # Add an image already in the archive -> stub entry
    r = client.post("/api/add/existing", json={"path": "a.png"})
    assert r.status_code == 200
    entry_id = r.json()["id"]

    # Detail shows the image with a servable URL
    detail = client.get(f"/api/entries/{entry_id}").json()
    assert detail["images"][0]["path"] == "./a.png"
    img_url = detail["images"][0]["url"]
    assert client.get(img_url).status_code == 200

    # Human alt edit is stored and protected
    r = client.post(f"/api/entries/{entry_id}/images/0/alt", json={"alt": "a grey test plate"})
    assert r.status_code == 200
    gen = client.post(f"/api/entries/{entry_id}/images/0/alt/generate").json()
    assert gen["ok"] is False and gen["needsConfirm"] is True  # won't clobber human edit

    # No API key in this environment -> honest signal on confirm
    gen2 = client.post(f"/api/entries/{entry_id}/images/0/alt/generate?confirm=true").json()
    assert gen2["ok"] is False and gen2["reason"] == "no_api_key"

    # Search finds it
    listing = client.get("/api/entries?q=grey").json()
    assert any(e["id"] == entry_id for e in listing["entries"])

    # PIAF produces a downloadable derivative and flags the image
    piaf = client.post(f"/api/entries/{entry_id}/images/0/piaf", json={"threshold": 128}).json()
    assert piaf["ok"] is True
    assert client.get(piaf["url"]).status_code == 200
    after = client.get(f"/api/entries/{entry_id}").json()
    assert after["images"][0]["tactilePrepped"] is True


def test_path_traversal_blocked(tmp_path):
    _png(tmp_path / "a.png")
    client = TestClient(app)
    client.post("/api/settings/archive", json={"path": str(tmp_path)})
    assert client.get("/api/image?path=../../etc/passwd").status_code == 400
