#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Data loading utilities for the GPI v5.1 pipeline."""

import json
from typing import Any, Dict


def load_json(path: str) -> Dict[str, Any]:
    """Load a JSON file and return its content."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
