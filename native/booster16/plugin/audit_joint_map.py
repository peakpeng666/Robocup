"""Static axis/name audit only. Not FK, dynamic, or closed-loop validation."""
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
root=Path(__file__).parent
source=(root/'BoosterK1Policy.cpp').read_text()
def table(name):
    block=re.search(r'\b'+name+r'=\{(.*?)\};',source,re.S)
    return re.findall(r'"([^"]+)"',block.group(1))
official=table('officialNames');scene=table('sceneNames')
if len(official)!=22 or len(scene)!=22 or len(set(official))!=22 or len(set(scene))!=22:
    raise RuntimeError('mapping not bijective22')
model=Path(sys.argv[1])
bhuman=root/'scenes/vendor/bhuman/K1.rsi3'
a={j.attrib['name']:j for j in ET.parse(model).iter('joint') if 'name' in j.attrib}
b={j.attrib['name']:j for j in ET.parse(bhuman).getroot().findall('Hinge') if 'name' in j.attrib}
rows=[]
for real,sim in zip(official,scene):
    r=a[real];s=b[sim];axis=s.find('Axis')
    axis_b=[float(axis.attrib.get(k,0)) for k in ['x','y','z']]
    axis_r=[float(v) for v in r.attrib['axis'].split()]
    if axis_b!=axis_r:raise RuntimeError('axis mismatch '+real)
    rows.append(dict(official=real,scene=sim,local_axis=axis_r,scene_init=s.find('Axis/Deflection').attrib.get('init','0'),official_range=r.attrib.get('range')))
print(json.dumps(dict(status='PASS',checked_joint_names_and_local_axes=22,
 model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
 bhuman_sha256=hashlib.sha256(bhuman.read_bytes()).hexdigest(),mapping=rows,
 limitations='Local axis correspondence only; no world-frame FK, joint zero offset, dynamic or gait qualification'),indent=2))
