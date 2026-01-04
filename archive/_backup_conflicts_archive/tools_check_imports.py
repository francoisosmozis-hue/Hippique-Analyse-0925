mods = ["p_finale_export","simulate_ev","simulate_wrapper","validator_ev",
        "runner_chain","pipeline_run","online_fetch_zeturf",
        "fetch_je_stats","fetch_je_chrono","update_excel_with_results",
        "get_arrivee_geny","drive_sync","module_dutching_pmu","prompt_analyse"]
for m in mods:
    try:
        __import__(m)
        print(f"OK import {m}")
    except Exception as e:
        print(f"FAIL import {m} -> {e}")
