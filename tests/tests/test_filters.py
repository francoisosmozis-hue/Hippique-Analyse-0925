def test_sp_filter_min_place_odds():
    from pipeline_run import filter_sp_candidates

    cands = [{"odds_place": 4.9}, {"odds_place": 5.0}]
    kept = filter_sp_candidates(cands)
    assert len(kept) == 1 and kept[0]["odds_place"] == 5.0


def test_cp_filter_sum_odds():
    from pipeline_run import filter_cp_candidates

    a = {"odds_place": 2.9}
    b = {"odds_place": 3.0}
    c = {"odds_place": 3.1}
    d = {"odds_place": 2.9}
    e = {"odds_place": 3.2}
    f = {"odds_place": 3.0}

    kept = filter_cp_candidates([(a, b), (c, d), (e, f)])
    assert len(kept) == 1 and kept[0] == (e, f)
