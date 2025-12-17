#!/bin/bash
set -e

# I001
ruff check scripts/analyse_payout_drift.py --fix
ruff check scripts/calculate_roi.py --fix

# PLC0415
# tests/conftest.py
sed -i "s/def app_with_mock_config(mock_config): # This fixture ensures app is imported AFTER mock_config is active\n    from hippique_orchestrator.service import app/def app_with_mock_config(mock_config):\n    return app/g" tests/conftest.py

# F401
# tests/test_validator_ev.py
sed -i "s/from pathlib import Path//g" tests/test_validator_ev.py

# B011
# tests/manual_run_check.py
sed -i "s/assert False, \"Connection to the server failed.\"/raise AssertionError(\"Connection to the server failed.\")/g" tests/manual_run_check.py
sed -i "s/assert False, f\"An unexpected error occurred: {e}\"/raise AssertionError(f\"An unexpected error occurred: {e}\")/g" tests/manual_run_check.py

# F841
# tests/test_service.py
sed -i "s/    mock_build_plan = mocker.patch(/    mocker.patch(/g" tests/test_service.py
# tests/test_update_excel_with_results.py
sed -i "s/    repo_root = Path(__file__).resolve().parent.parent//g" tests/test_update_excel_with_results.py

# E402
# scripts/analyse_payout_drift.py
sed -i "s/sys.path.append(str(project_root))\n\nfrom hippique_orchestrator import firestore_client/from hippique_orchestrator import firestore_client\nsys.path.append(str(project_root))/g" scripts/analyse_payout_drift.py
# scripts/calculate_roi.py
sed -i "s/sys.path.append(str(project_root))\n\nfrom hippique_orchestrator import firestore_client/from hippique_orchestrator import firestore_client\nsys.path.append(str(project_root))/g" scripts/calculate_roi.py

# E701
# scripts/calculate_roi.py
sed -i "s/        if \"CG\" not in results: return False/        if \"CG\" not in results:\n            return False/g" scripts/calculate_roi.py
sed -i "s/        if \"TRIO\" not in results: return False/        if \"TRIO\" not in results:\n            return False/g" scripts/calculate_roi.py
sed -i "s/        if \"ZE4\" not in results: return False/        if \"ZE4\" not in results:\n            return False/g" scripts/calculate_roi.py


echo "Ruff fixes applied."