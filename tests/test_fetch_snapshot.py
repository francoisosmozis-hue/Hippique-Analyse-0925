from typing import Any


def test_fetch_race_snapshot_returns_list_of_partants(monkeypatch):
    import online_fetch_zeturf as ofz

    fake_payload = {
        "runners": [{"num": "1", "name": "Alpha"}],
        "meeting": "Test",
        "discipline": "Plat",
    }

   captured: dict[str, Any] = {}

    def fake_parse(url: str, *, snapshot: str) -> dict[str, Any]:
        captured["url"] = url
        captured["snapshot"] = snapshot
        return dict(fake_payload)

    def fake_normalize(payload: dict[str, Any]) -> dict[str, Any]:
        captured["normalized"] = payload
        return {"runners": payload["runners"], "partants": len(payload["runners"]) }

    monkeypatch.setattr(ofz._impl, "parse_course_page", fake_parse, raising=False)
    monkeypatch.setattr(ofz._impl, "normalize_snapshot", fake_normalize, raising=False)

    snap = ofz.fetch_race_snapshot("R1", "C1", "H5", url="https://example.com/course/mock")

    assert isinstance(snap["partants"], list)
    assert snap["phase"] == "H5"
    assert snap["market"] == {}
    assert captured["snapshot"] == "H5"
    assert captured["url"].endswith("/R1C1")
