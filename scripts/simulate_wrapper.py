try:
    from simulate_wrapper import validate_exotics_with_simwrapper
except Exception:
    def validate_exotics_with_simwrapper(*_args, **_kwargs):
        return {"ok": False, "reason": "simulate_wrapper unavailable"}
