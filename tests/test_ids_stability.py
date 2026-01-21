# tests/test_ids_stability.py
from hippique_orchestrator.contracts.ids import make_race_uid, make_runner_uid, normalize_name

def test_normalize_name():
    assert normalize_name("  Chévâl-UN  ") == "CHEVAL UN"
    assert normalize_name("J.C. Dupont") == "J C DUPONT"

def test_race_uid_is_stable():
    """Ensures that for the same inputs, the race_uid is identical."""
    uid1 = make_race_uid("2025-12-25", "VINCENNES", 1, "ATTELE", 2700, "2025-12-25T13:50:00")
    uid2 = make_race_uid("2025-12-25", "VINCENNES", 1, "ATTELE", 2700, "2025-12-25T13:50:00")
    assert uid1 == uid2

def test_race_uid_is_sensitive_to_changes():
    """Ensures that any change in input results in a different uid."""
    uid_base = make_race_uid("2025-12-25", "VINCENNES", 1, "ATTELE", 2700, "13:50")
    uid_diff_dist = make_race_uid("2025-12-25", "VINCENNES", 1, "ATTELE", 2850, "13:50")
    assert uid_base != uid_diff_dist

def test_runner_uid_is_stable():
    race_uid = "some_stable_race_uid"
    uid1 = make_runner_uid(race_uid, 1, "CHEVAL UN")
    uid2 = make_runner_uid(race_uid, 1, "CHEVAL UN")
    assert uid1 == uid2