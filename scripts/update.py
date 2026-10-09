#!/usr/bin/env python3
"""Bootstrap the updater from a fresh kit checkout for an existing project."""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin/wiki'))
from _update import main


if __name__ == '__main__':
    raise SystemExit(main())
