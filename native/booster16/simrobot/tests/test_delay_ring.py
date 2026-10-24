#!/usr/bin/env python3
"""Focused regression against pinned upstream source, NOT a SimRobot build/test.

Usage: python3 test_delay_ring.py /path/to/SimRobot
Reads the exact pinned Git objects, never changes the supplied checkout. Applies
both optional patches in temporary trees, then compiles the actual extracted
ring loops with checked indexing. The old bug raises before any invalid access.
Requires git and a C++17 compiler (CXX or g++).
"""
import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

PIN = '9deb6ae6b2a553211612affb757490736f96bfb3'
SOURCE = 'Src/SimRobotCore3/Simulation/Motors/ServoMotor.cpp'
HEADER = 'Src/SimRobotCore3/Simulation/Motors/ServoMotor.h'
BASE = Path(__file__).resolve().parents[2]


def run(*args, **kwargs):
    return subprocess.run(*args, check=True, text=True, **kwargs)


def read_pinned(repo, name):
    return run(['git', '-C', str(repo), 'show', PIN + ':' + name],
               stdout=subprocess.PIPE).stdout


def extract_loop(source):
    matches = re.findall(r'  unsigned searchIndex = index;\n  while\(true\)\n  \{.*?\n  \}\n(?=\n  index\+\+;)',
                         source, re.DOTALL)
    if len(matches) != 1:
        raise RuntimeError('Pinned source shape changed: expected one delay ring loop')
    return matches[0]


def patched_tree(root, original, patches):
    for name, text in original.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    for patch in patches:
        run(['git', 'apply', '--check', str(patch)], cwd=root)
        run(['git', 'apply', str(patch)], cwd=root)
    return {str(p.relative_to(root)): p.read_text()
            for p in root.rglob('*') if p.is_file()}


PRELUDE = r'''
#include <cstddef>
#include <iostream>
#include <stdexcept>
#include <vector>
struct NextTargets { float setPoint = 0; float executionTimestamp = 0; };
struct Simulation {
  double simulatedTime = 1.;
  static Simulation* simulation;
};
Simulation sim;
Simulation* Simulation::simulation = &sim;
struct CheckedTargets {
  std::vector<NextTargets> values;
  std::vector<unsigned> visits;
  NextTargets& operator[](unsigned i) {
    // Check first: never execute the upstream out-of-bounds read.
    if(i >= values.size()) throw std::out_of_range("target index");
    if(visits.size() > 4 * values.size()) throw std::runtime_error("nonterminating loop");
    visits.push_back(i);
    return values.at(i);
  }
};
'''


def function(name, loop):
    # Equal execution timestamps force the original condition's second term to
    # false, hence exactly two reads per visited slot, with no target assignment.
    return ('std::vector<unsigned> ' + name + '(unsigned targetSize, unsigned index) {\n'
            '  CheckedTargets target{std::vector<NextTargets>(targetSize), {}};\n'
            '  NextTargets lastExecutedSetpoint;\n' + loop + '\n'
            '  return target.visits;\n}\n')


MAIN = r'''
int main() {
  unsigned cases = 0;
  for(unsigned size : {1u, 2u, 10u}) for(unsigned start = 0; start < size; ++start) {
    bool caught = false;
    try { (void)originalLoop(size, start); }
    catch(const std::out_of_range&) { caught = true; }
    if(!caught) throw std::runtime_error("Original defect not reproduced");
    const auto visits = fixedLoop(size, start);
    if(visits.size() != 2 * size) throw std::runtime_error("Wrong visit count");
    for(unsigned step = 0; step < size; ++step) {
      const unsigned expected = (start + step) % size;
      if(visits[2 * step] != expected || visits[2 * step + 1] != expected)
        throw std::runtime_error("Wrong ring ordering");
    }
    ++cases;
  }
  std::cout << "PASS " << cases << " original bounds violations safely caught; "
            << cases << " patched traversals bounded and ordered\n";
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('upstream', type=Path, help='existing SimRobot Git checkout containing pinned commit')
    args = parser.parse_args()
    original = {name: read_pinned(args.upstream, name) for name in (SOURCE, HEADER)}
    delay = BASE / 'patches/simrobot-9deb6ae6-delay-ring.patch'
    hybrid = BASE / 'patches/simrobot-9deb6ae6-hybrid-actuator.patch'
    with tempfile.TemporaryDirectory(prefix='simrobot-delay-ring-') as tmp:
        tmp = Path(tmp)
        standalone = patched_tree(tmp / 'standalone', original, [delay])
        before = patched_tree(tmp / 'before', original, [delay, hybrid])
        after = patched_tree(tmp / 'after', original, [hybrid, delay])
        if before != after:
            raise RuntimeError('Patch order changed resulting source tree')
        old_loop = extract_loop(original[SOURCE])
        new_loop = extract_loop(standalone[SOURCE])
        if new_loop != old_loop.replace('searchIndex > targetSize', 'searchIndex >= targetSize'):
            raise RuntimeError('Unexpected change beyond wrap condition')
        if extract_loop(before[SOURCE]) != new_loop:
            raise RuntimeError('Hybrid patch changed fixed loop')
        print('PASS standalone patch and both hybrid patch orders; resulting trees identical', flush=True)
        cpp = tmp / 'checked_delay_ring.cpp'
        cpp.write_text(PRELUDE + function('originalLoop', old_loop) + function('fixedLoop', new_loop) + MAIN)
        compiler = shlex.split(os.environ.get('CXX', 'g++'))
        for mode, flags in [('debug', ['-O0', '-g']), ('release', ['-O2', '-DNDEBUG'])]:
            executable = tmp / mode
            run(compiler + ['-std=c++17', '-Wall', '-Wextra', '-Wpedantic', '-Werror'] + flags
                + [str(cpp), '-o', str(executable)])
            print(mode + ':', flush=True)
            run([str(executable)])
    print('Scope: extracted upstream ring loop only; no complete SimRobot or physics validation.')


if __name__ == '__main__':
    main()
