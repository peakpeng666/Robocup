#!/usr/bin/env python3
"""Retired workspace-removal command. Runnable RoboCup workspaces must remain local."""
import argparse,json

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Retired; workspace deletion is refused.')
    args=parser.parse_args()
    message='Workspace deletion is retired by explicit user policy. Keep match, MuJoCo sim2sim and training workspaces locally; routine cleanup is limited to disposable caches and verified duplicates.'
    if args.apply:parser.error(message)
    print(json.dumps({'status':'RETIRED','deletion_performed':False,'policy':message},indent=2))

if __name__=='__main__':main()
