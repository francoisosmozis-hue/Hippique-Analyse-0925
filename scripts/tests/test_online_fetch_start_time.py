from scripts import online_fetch_zeturf as zeturf


def test_extract_start_time_from_time_tag(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    html = """
    <html>
      <body>
        <time datetime="2023-09-25T13:45:00+00:00"></time>
      </body>
    </html>
    """
    assert zeturf._extract_start_time(html) == "13:45"


def test_extract_start_time_from_text(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    html = """
    <div class="course-header">
      Heure de départ : <strong>14h35</strong>
    </div>
    """
    assert zeturf._extract_start_time(html) == "14:35"


def test_extract_start_time_with_parenthetical_suffix(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    html = """
    <div class="course-header">
      Heure de départ : <strong>14h35 (GMT+2)</strong>
    </div>
    """
    assert zeturf._extract_start_time(html) == "14:35"


def test_extract_start_time_from_plain_html(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    html = """
    <html>
      <head>
        <title>Course</title>
      </head>
      <body>
        Départ prévu à 9h.
      </body>
    </html>
    """
    assert zeturf._extract_start_time(html) == "09:00"


def test_extract_start_time_from_json_ld(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "HorseRace",
          "startDate": "2023-09-25T18:20:00+02:00"
        }
        </script>
      </head>
      <body></body>
    </html>
    """
    assert zeturf._extract_start_time(html) == "18:20"


def test_fetch_runners_scrapes_start_time(monkeypatch):
    payload = {"meta": {}, "runners": []}

    class DummyResponse:
        def json(self):
            return payload

        def raise_for_status(self):
            return None

    def fake_get(url, *args, **kwargs):
        return DummyResponse()

    monkeypatch.setattr(zeturf.requests, "get", fake_get)
    monkeypatch.setattr(zeturf, "_scrape_start_time_from_course_page", lambda course_id: "13:45")

    result = zeturf.fetch_runners("https://www.zeturf.fr/race/123456")

    assert result["meta"]["start_time"] == "13:45"
    assert result["start_time"] == "13:45"

