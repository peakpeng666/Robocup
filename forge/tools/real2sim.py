#!/usr/bin/env python3
"""Inspect a component profile or independently audit a completed platform run."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from forge.real2sim import resolve_profile, run_contract, audit_ports


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    inspect=sub.add_parser('inspect');inspect.add_argument('profile',type=Path)
    audit=sub.add_parser('audit');audit.add_argument('run',type=Path)
    parser.add_argument('--output',type=Path,help='new immutable receipt path')
    args=parser.parse_args()
    if args.command=='inspect':
        p=resolve_profile(args.profile)
        report=run_contract(p['simulator'],p['application'],p['artifacts'])
        report['profile']=str(args.profile.resolve())
    else:
        report=audit_ports(args.run,json.loads((args.run/'adapter-contract.json').read_text()))
    if args.output:
        with args.output.open('x') as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 1 if report.get('status')=='FAIL' else 0


if __name__=='__main__':raise SystemExit(main())
