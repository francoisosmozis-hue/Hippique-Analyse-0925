import re


def test_fetch_race_snapshot_returns_list_of_partants(monkeypatch):
    import online_fetch_zeturf as ofz

    fake_payload = {
        "runners": [{"num": "1", "name": "Alpha"}],
        "meeting": "Test",
        "discipline": "Plat",
    }

    monkeypatch.setattr(ofz, "_double_extract", lambda *a, **k: dict(fake_payload), raising=False)
    monkeypatch.setattr(
        ofz,
        "_fetch_snapshot_via_html",
        lambda *_a, **_k: dict(fake_payload),
        raising=False,
    )
    monkeypatch.setattr(ofz._impl, "_extract_course_id_from_entry", lambda *_a: None, raising=False)
    monkeypatch.setattr(ofz._impl, "_extract_url_from_entry", lambda *_a: None, raising=False)
    monkeypatch.setattr(ofz._impl, "_COURSE_ID_PATTERN", re.compile(r"(?!)"), raising=False)
    monkeypatch.setattr(ofz._impl, "fetch_race_snapshot", lambda *a, **k: {}, raising=False)

    snap = ofz.fetch_race_snapshot("R1", "C1", "H5", url="https://example.com/course/mock")

    assert isinstance(snap["partants"], list)
    assert snap["phase"] == "H5"
    assert snap["rc"] == "R1C1"
