#!/usr/bin/env python3
"""New pinned changed-code experiment; never the Issue3 or previous SC5 ELF."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.e62_sc5_candidate_regression import main
CANDIDATE='d7a44dcda4f836ec6da15b19398af092cc79ff102b54778b0cd58bb245f9cba6'
SOURCE='759a558b0714547b45fffc56b6a76ebd25efa575'
if __name__=='__main__':raise SystemExit(main(CANDIDATE,SOURCE,'CHANGED_CODE_SC5_NEW_EXPERIMENT_NOT_ISSUE3_OR_ORIGINAL'))
