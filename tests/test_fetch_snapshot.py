import json
import shutil
from pathlib import Path
from typing import Any


def test_fetch_race_snapshot_returns_list_of_partants(monkeypatch: Any) -> None:
    import online_fetch_zeturf as ofz

    fake_payload = {
        "runners": [{"num": "1", "name": "Alpha"}],
        "meeting": "Test",
        "discipline": "Plat",
        "date": "2023-09-25",
    }

    captured: dict[str, Any] = {}

    rc_dir = Path("data") / "R1C1"
    h30_payload = {"1": {"odds_win": 3.4, "odds_place": 1.6}}

    try:
        rc_dir.mkdir(parents=True, exist_ok=True)
        (rc_dir / "h30.json").write_text(json.dumps(h30_payload), encoding="utf-8")

    def fake_parse(url: str, *, snapshot: str) -> dict[str, Any]:
            captured["url"] = url
            captured["snapshot"] = snapshot
            return dict(fake_payload)

    sdef fake_normalize(payload: dict[str, Any]) -> dict[str, Any]:
            captured["normalized"] = payload
            return {
                "runners": payload["runners"],
                "partants": len(payload["runners"]),
            }

        def failing_impl_fetch(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("impl failure")

        def fake_http_get(_url: str, session: Any | None = None) -> str:
            return "<html></html>"

        monkeypatch.setattr(ofz._impl, "parse_course_page", fake_parse, raising=False)
        monkeypatch.setattr(ofz._impl, "normalize_snapshot", fake_normalize, raising=False)
        monkeypatch.setattr(ofz._impl, "fetch_race_snapshot", failing_impl_fetch, raising=False)
        monkeypatch.setattr(ofz, "_http_get", fake_http_get)

        snap = ofz.fetch_race_snapshot("R1", "C1", "H5", url="https://example.com/course/mock")

        assert isinstance(snap["partants"], list)
        assert snap["phase"] == "H5"
        assert snap["market"] == {}
        assert snap["partants_count"] == 1
        assert snap["meeting"] == "Test"
        assert snap["discipline"] == "Plat"
        assert "meta" in snap and snap["meta"]["phase"] == "H5"
        assert snap["meta"]["date"] == "2023-09-25"
        assert snap["runners"][0]["odds_win_h30"] == 3.4
        assert snap["runners"][0]["odds_place_h30"] == 1.6
        assert captured["snapshot"] == "H-5"
        assert captured["url"] == "https://example.com/course/mock"
    finally:
        shutil.rmtree(rc_dir, ignore_errors=True)
    
