@@ -176,25 +176,40 @@ def test_green_flag_true_when_thresholds_met() -> None:
 @pytest.mark.parametrize(
     "tickets,budget,expected_reasons",
     [
         ([{"p": 0.65, "odds": 2.0}], 100, ["EV ratio below 0.40"]),
         (
             [{"p": 0.55, "odds": 2.0}],
             100,
             ["EV ratio below 0.40", "ROI below 0.20"],
         ),
         (
             [{"p": 0.8, "odds": 2.5, "legs": ["leg1", "leg2"]}],
             10,
             ["expected payout for combined bets ≤ 10€"],
         ),
     ],
 )
 def test_green_flag_failure_reasons(
     tickets: List[dict[str, Any]], budget: float, expected_reasons: List[str]
 ) -> None:
     """Check that failing criteria produce the appropriate reasons."""
     res = compute_ev_roi(tickets, budget=budget)
 
     assert res["green"] is False
     assert res["failure_reasons"] == expected_reasons
 
+
+def test_clv_computation() -> None:
+    """CLV should be computed per ticket and averaged."""
+    tickets = [
+        {"p": 0.5, "odds": 2.0, "closing_odds": 1.8},
+        {"p": 0.4, "odds": 3.0, "closing_odds": 3.3},
+    ]
+
+    res = compute_ev_roi(tickets, budget=100)
+
+    assert tickets[0]["clv"] == pytest.approx((1.8 - 2.0) / 2.0)
+    assert tickets[1]["clv"] == pytest.approx((3.3 - 3.0) / 3.0)
+    expected = ((1.8 - 2.0) / 2.0 + (3.3 - 3.0) / 3.0) / 2
+    assert res["clv"] == pytest.approx(expected)
+
