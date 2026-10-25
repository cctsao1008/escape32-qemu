#!/usr/bin/env python3
"""Legacy G13B4 CLI compatibility entrypoint.

Current autonomous T01/T02 implementation is tests/functional_dshot_sitl.py.
Keep this file to preserve old scripts, docs and pinned regression calls.
"""
from functional_dshot_sitl import (
    _checked_symbols, _make_stage_records, _stage_index, _guest_values,
    _run_guest, main,
)
if __name__ == "__main__":
    main()
