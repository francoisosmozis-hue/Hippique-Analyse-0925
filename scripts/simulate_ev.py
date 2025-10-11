<<<<<<< HEAD
# CI shim: expose simulate_ev_batch via le module racine si présent.
try:
    from simulate_ev import simulate_ev_batch  # module racine
except Exception:
    def simulate_ev_batch(*_args, **_kwargs):
        # Fallback neutre pour tests qui ne l'exécutent pas réellement
        return []
=======
"""Compat helper to expose root simulate_ev module under scripts namespace."""

from simulate_ev import *  # noqa: F401,F403
>>>>>>> origin/main
