#!/usr/bin/env python3
"""Inspect deterministic scenario intents; does not execute firmware."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.functional_dshot_scenario import load_scenario


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--id', required=True)
    p.add_argument('--preview', type=int, default=6)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    if not 0 <= args.preview <= 100:
        p.error('--preview must be 0..100')
    scenario = load_scenario(args.plan, args.id)
    result = scenario.summary()
    result['first_frames'] = [scenario.frame(i).as_dict()
                              for i in range(min(args.preview, scenario.total_frames))]
    result['last_frame'] = scenario.frame(scenario.total_frames-1).as_dict()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print('E62_DSHOT_SCENARIO_COMPILED ' + json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
