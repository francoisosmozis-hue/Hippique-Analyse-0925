
import pytest

from src import plan


class DummyResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


ZETURF_HTML = """
<html>
  <body>
    <div class="meeting">
      <a href="/fr/course/2023-09-30/R1C1-prix-special" data-meeting="Paris-Vincennes" data-time="12:00">Course 1</a>
      <a href="/fr/course/2023-09-30/R1C1-prix-special" data-meeting="Paris-Vincennes" data-time="12:00">Duplicate should be ignored</a>
    </div>
    <div class="meeting">
      <a href="/fr/course/2023-09-30/R1C2-prix" data-meeting="Paris-Vincennes">Course 2</a>
    </div>
  </body>
</html>
"""

GENY_HTML = """
<html>
  <body>
    <div data-race="R1C2" data-time="12:35">12:35</div>
  </body>
</html>
"""


@pytest.fixture(autouse=True)
def reset_throttle():
    plan._LAST_REQUEST_BY_HOST.clear()


def test_build_plan_fills_missing_time(monkeypatch):
    def fake_get(url, headers=None, timeout=0):
        if "zeturf" in url:
            return DummyResponse(ZETURF_HTML)
        if "geny" in url:
            return DummyResponse(GENY_HTML)
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(plan.requests, "get", fake_get)

    result = plan.build_plan("2023-09-30")
    assert len(result) == 2
    assert result[0]["c_label"] == "C1"
    assert result[0]["time_local"] == "12:00"
    assert result[1]["c_label"] == "C2"
    assert result[1]["time_local"] == "12:35"
