#!/usr/bin/env python3
"""Exercise original visual-kick IDL/handler in the isolated original ARM graph.

Repeated empty/nonempty frame IDs exercise original IDL allocation/destruction.
This verifies transport, not a physical kick.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge import paths, util
from run_booster_native import new_work, prepare_graph, sandbox_command


def run(artifacts):
    work = new_work('visual-kick-original-handler-contract')
    prepare_graph(work)
    binary = work / 'host-probe'
    compile_ = ['c++','-std=c++17','-O2','-I',str(paths.FORGE/'native'),
                str(paths.FORGE/'native/test_fw16_session.cpp'),'-o',str(binary)]
    with (work/'host-build.log').open('w') as log:
        subprocess.run(compile_,stdout=log,stderr=subprocess.STDOUT,check=True)
    command = sandbox_command(work,['/controller/mck','-c','-s','105','/opt/booster/Gait/forge_sim.lua'],
        preload=artifacts['io'],rpc=artifacts['rpc'],physics=artifacts['physics'],controller_graph=True)
    host = [str(binary),str(work/'output'),'sdkvisualstressnative']
    with (work/'native.log').open('w') as log:
        process = subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            result = subprocess.run(host,capture_output=True,text=True,timeout=60)
            (work/'host.log').write_text(result.stdout+result.stderr)
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                process.wait(timeout=10)
    text = (work/'native.log').read_text(errors='replace')
    report = {'schema':'forge.original-visual-kick-contract/1','work':str(work),
        'scope':'67 frozen cycles; 64 original IDL allocation/handler/destruction calls, alternating empty and nonempty frame IDs; no physical action qualification',
        'host_exit':result.returncode,'native_exit':process.returncode,
        'original_handler_invocations':text.count('FORGE_FW16_VISUAL_KICK tick='),
        'commands':[compile_,command,host], 'robot_connected':False,
        'host_sha256':util.sha256_file(binary),
        'adapters':{k:{'path':str(v),'sha256':util.sha256_file(v)} for k,v in artifacts.items()}}
    report['status'] = 'PASS' if result.returncode == process.returncode == 0 and report['original_handler_invocations'] == 64 else 'FAIL'
    util.write_json(work/'result.json',report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts',type=Path,required=True)
    args = parser.parse_args()
    artifacts = {k:Path(v).resolve(strict=True) for k,v in json.loads(args.artifacts.read_text()).items()}
    if set(artifacts) != {'io','rpc','physics'}: parser.error('io, rpc and physics required')
    result = run(artifacts)
    print(json.dumps(result,indent=2))
    raise SystemExit(result['status'] != 'PASS')
