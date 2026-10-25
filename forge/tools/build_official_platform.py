#!/usr/bin/env python3
"""Build only the independent simulator IO plugin, reusing the verified core/A."""
import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from forge import builds,paths,util
from make_official_team_patch import write_patch,CORE


def build(name, core_name):
    receipt=paths.RUNS/'platform-builds'/util.stamp();receipt.mkdir(parents=True)
    patch=receipt/'platform.patch';write_patch(patch)
    builds.create_variant(name,[str(patch)],'Independent negotiated K1 platform port; original A controller and physics core reused')
    root=builds.variant_root(name);core=builds.variant_root(core_name)
    for p in (root/CORE).rglob('*'):
        if p.is_file() and util.sha256_file(p)!=util.sha256_file(core/p.relative_to(root)):
            raise ValueError('the selected core does not implement the identical actuator source contract')
    commands=[['cmake','-S',str(root/'Make/CMake'),'-B',str(root/'_builds/platform-Release'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release'],
              ['cmake','--build',str(root/'_builds/platform-Release'),'--target','OfficialTeam','--parallel','4']]
    for index,command in enumerate(commands):
        with (receipt/f'build-{index}.log').open('x') as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    binary=root/'Build/Linux/SimRobot/Release'
    (binary/'libSimRobotCore3.so').symlink_to(core/'Build/Linux/SimRobot/Release/libSimRobotCore3.so')
    result={'status':'PASS','commands':commands,'baseline_controller_rebuilt':False,'core_source_identical':True,
            'library':str(binary/'libOfficialTeam.so'),'sha256':util.sha256_file(binary/'libOfficialTeam.so'),
            'core':str((binary/'libSimRobotCore3.so').resolve()),'receipt':str(receipt)}
    util.write_json(receipt/'result.json',result)
    return result


if __name__=='__main__':
    import json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name');parser.add_argument('--core-variant',default='official-team-independent-20261023-d')
    args=parser.parse_args();print(json.dumps(build(args.name,args.core_variant),indent=2))
