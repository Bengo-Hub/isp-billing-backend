#!/usr/bin/env python
"""Compatibility shim: exposes scripts/tools/drop_db as scripts/drop_db
This keeps existing scripts and CI that call `python scripts/drop_db.py` working.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from tools.drop_db import main

if __name__ == '__main__':
    main()
