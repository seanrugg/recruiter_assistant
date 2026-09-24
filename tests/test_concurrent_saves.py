"""Importing a list fires many saves at once. None may be lost.

Before the write lock, adding 23 coaches in one go kept only 20."""
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from recruiting_desk import app as app_module
from recruiting_desk import campaign


def test_many_simultaneous_app_saves_all_land():
    client = TestClient(app_module.app)

    def save(i):
        r = client.put(f"/api/db/targets/t{i}", json={"data": {"id": f"t{i}", "school": f"School {i}"}})
        assert r.status_code == 200

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(save, range(60)))
    docs = client.get("/api/db/targets").json()["docs"]
    assert len([k for k in docs if k.startswith("t")]) == 60


def test_many_simultaneous_campaign_saves_all_land():
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda i: campaign.save_program(f"c{i}", {"school": f"S{i}"}), range(60)))
    assert len([k for k in campaign.programs() if k.startswith("c")]) == 60
