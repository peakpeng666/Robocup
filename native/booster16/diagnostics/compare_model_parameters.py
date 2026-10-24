"""Read-only source parameter comparison, not a causal identification experiment."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
p=argparse.ArgumentParser();p.add_argument('--assets',type=Path,default=Path('/workspace/shared/booster-assets-upstream'));p.add_argument('--simrobot',type=Path,default=Path('/workspace/shared/simrobot-upstream'));args=p.parse_args()
base=Path(__file__).resolve().parents[1];bpath=base/'plugin/scenes/vendor/bhuman/K1.rsi3';opath=args.assets/'robots/K1/K1_22dof.xml'
bxml=ET.parse(bpath).getroot();oxml=ET.parse(opath).getroot()
source=(base/'plugin/BoosterK1Policy.cpp').read_text()
def table(name):return re.findall(r'"([^"]+)"',re.search(r'\b'+name+r'=\{(.*?)\};',source,re.S).group(1))
pairs=list(zip(table('officialNames'),table('sceneNames')))
sys.path.insert(0,str(base/'vendor/booster_deploy'))
from tasks.locomotion.robots.k1 import K1WalkTaskCfg
cfg=K1WalkTaskCfg()
def unit(s):
 m=re.fullmatch(r'([+\-0-9.eE]+)(.*)',s);n=float(m[1]);suffix=m[2]
 factors={'':1.,'g':.001,'kg':1.,'mm':.001,'m':1.,'g*mm^2':1e-9,'kg*m^2':1.,'degree':math.pi/180}
 return n*factors[suffix]
def quat_rotation(q):
 w,x,y,z=q;n=math.sqrt(sum(v*v for v in q));w,x,y,z=[v/n for v in q]
 return [[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)], [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)], [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
def official_inertia(body):
 e=body.find('inertial');d=[float(v) for v in e.attrib['diaginertia'].split()];R=quat_rotation([float(v) for v in e.attrib.get('quat','1 0 0 0').split()])
 return dict(mass_kg=float(e.attrib['mass']),com_m=[float(v) for v in e.attrib['pos'].split()],inertia_body_kg_m2=[[sum(R[i][k]*d[k]*R[j][k] for k in range(3)) for j in range(3)] for i in range(3)])
def bhuman_inertia(body):
 e=body.find('InertiaMatrixMass');a=e.attrib;v={k:unit(a[k]) for k in ['ixx','iyy','izz','ixy','ixz','iyz']}
 return dict(mass_kg=unit(a['value']),com_m=[unit(a[k]) for k in ['x','y','z']],inertia_body_kg_m2=[[v['ixx'],v['ixy'],v['ixz']],[v['ixy'],v['iyy'],v['iyz']],[v['ixz'],v['iyz'],v['izz']]])
obody={j.attrib['name']:body for body in oxml.iter('body') for j in body.findall('joint') if 'name' in j.attrib}
bhinge={e.attrib['name']:e for e in bxml.findall('Hinge')}
omotor={e.attrib['joint']:e for e in oxml.find('actuator')}
rows=[]
for index,(official,scene) in enumerate(pairs):
 o=obody[official];h=bhinge[scene];b=h.find('Body');j=o.find("joint[@name='"+official+"']");axis=h.find('Axis');servo=axis.find('ServoMotor');d=axis.find('Deflection');effort=cfg.robot.effort_limit[index]
 ofin=[float(v) for v in omotor[official].attrib['forcerange'].split()];bforce=unit(servo.attrib['maxForce'])
 rows.append(dict(official_joint=official,bhuman_joint=scene,official_body=official_inertia(o),bhuman_body=bhuman_inertia(b),official_armature=float(j.attrib.get('armature','0')),bhuman_armature=unit(servo.attrib.get('armature','0')),official_range_rad=[float(v) for v in j.attrib['range'].split()],bhuman_range_rad=[unit(d.attrib[k]) for k in ['min','max']],official_initial_q_rad=cfg.robot.default_joint_pos[index],bhuman_initial_q_rad=unit(d.attrib.get('init','0')),official_task_effort_limit_nm=effort,official_model_force_range_nm=ofin,bhuman_model_max_force_nm=bforce,effective_symmetric_policy_limit_official_nm=min(effort,-ofin[0],ofin[1]),effective_symmetric_policy_limit_bhuman_nm=min(effort,bforce)))
trunk=dict(official=official_inertia(oxml.find("worldbody/body[@name='trunk']")),bhuman=bhuman_inertia(bxml.find("Body[@name='K1']")))
report=dict(model_sources={'official_xml':str(opath),'official_sha256':hashlib.sha256(opath.read_bytes()).hexdigest(),'bhuman_xml':str(bpath),'bhuman_sha256':hashlib.sha256(bpath.read_bytes()).hexdigest()},trunk=trunk,linked_body_mass_kg={'official':trunk['official']['mass_kg']+sum(r['official_body']['mass_kg'] for r in rows),'bhuman':trunk['bhuman']['mass_kg']+sum(r['bhuman_body']['mass_kg'] for r in rows)},joints=rows,all_effective_policy_torque_limits_equal=all(r['effective_symmetric_policy_limit_official_nm']==r['effective_symmetric_policy_limit_bhuman_nm'] for r in rows),all_inertia_values_are_body_frame_about_COM=True,initial_root_height_m={'official_cfg':cfg.mujoco.init_pos[2],'bhuman_test_scene':.537},contact_source_notes={'official_geom_default':oxml.find('default/geom').attrib,'official_ground':oxml.find("worldbody/geom[@name='ground']").attrib,'official_option_xml':oxml.find('option').attrib,'official_runtime_timestep_s':cfg.mujoco.physics_dt,'bhuman':'Core3 Geometry.cpp sets condim3, sliding friction1, torsional/rolling0 unless Material overrides; model defaults supply solref/solimp. Actual mixed contact friction must be measured, not inferred from ground alone.','solver_bhuman':'Simulation.cpp sets Euler,50 iterations,tolerance1e-6,Newton,jacobian auto; source does not override default impratio.'},limitations=['parameter differences are not causal attribution','physical joint references and body inertias must not be silently changed to improve tracking','initial poses and MuJoCo library versions are separate confounds','no model/PD/policy files were edited'])
a=trunk['official']['inertia_body_kg_m2'];b=trunk['bhuman']['inertia_body_kg_m2']
report['high_signal_differences']={'trunk_Ixx_ratio_bhuman_to_official':b[0][0]/a[0][0],'trunk_Iyy_ratio_bhuman_to_official':b[1][1]/a[1][1],'head_armature_ratio':rows[0]['bhuman_armature']/rows[0]['official_armature'],'arm_armature_ratio':rows[2]['bhuman_armature']/rows[2]['official_armature'],'head_yaw_mount_height_m':{'official':float(obody['aahead_yaw_joint'].attrib['pos'].split()[2]),'bhuman':unit(bxml.find("Body[@name='K1']/Hinge[@ref='HeadYaw']/Translation").attrib['z'])},'effective_control_torque_cap_change':not report['all_effective_policy_torque_limits_equal'],'mass_change':abs(report['linked_body_mass_kg']['official']-report['linked_body_mass_kg']['bhuman'])>1e-10}
print(json.dumps(report,indent=2))
