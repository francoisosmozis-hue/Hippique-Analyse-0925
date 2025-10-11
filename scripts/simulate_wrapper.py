<<<<<<< HEAD
try:
    from simulate_wrapper import validate_exotics_with_simwrapper
except Exception:
    def validate_exotics_with_simwrapper(*_args, **_kwargs):
        return {"ok": False, "reason": "simulate_wrapper unavailable"}
=======
"""Compat helper to reuse root simulate_wrapper module from scripts package."""

from simulate_wrapper import *  # noqa: F401,F403
>>>>>>> origin/main
