from .drive_sync_impl import *  # noqa: F401,F403
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="drive_sync wrapper")
    p.add_argument("--help-only", action="store_true")
    p.parse_args()
