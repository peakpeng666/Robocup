"""Evidence-backed equivalence levels; hardware remains explicitly unverified."""
import json
from pathlib import Path

from . import identity, util, config


def matrix(app):
    jobs = app.db.query("SELECT * FROM jobs ORDER BY created_at DESC")

    def proof(kind):
        for row in jobs:
            if row['type'] != kind or row['status'] != 'succeeded' or row['quality_verdict'] != 'PASS':
                continue
            if app.jobs.evidence_status(row) != 'VERIFIED':
                continue
            row['result'] = json.loads(row['result_json'] or '{}')
            if kind == 'arm_build' and identity.file_identity(row['result'].get('elf','')) != row['result'].get('sha256'):
                continue
            if kind == 'bundle_offline' and identity.file_identity(row['result'].get('bundle','')) != row['result'].get('bundle_sha256'):
                continue
            return row
        return None

    live = identity.current()
    rows = []
    cfg=config.project()
    l0 = live['official_contract_matches'] and live['training_source'] == cfg['chains']['training']['source_fingerprint']
    l0 = l0 and all(identity.file_identity(config.rp(cfg['models'][key])) == cfg['expected_hashes'][key+'_sha256'] for key in ('walk_pth','walk_onnx_match'))
    rows.append({'level':'L0 资产身份','definition':'当前源码、受保护文件、模型与配置的内容身份',
        'status':'VERIFIED' if l0 else 'STALE',
        'evidence':live['training_source'], 'gap':'范围为当前登记文件；不代表全部第三方/环境都已认证'})
    parity, cpp = proof('mujoco_verify_policy'), proof('contract_walk_cpp')
    cpp_parity = util.read_json(Path(cpp['run_dir'])/'cpp-network-parity.json') if cpp else None
    rows.append({'level':'L1 网络数值','definition':'相同实际输入的跨后端输出',
        'status':'VERIFIED' if parity and cpp_parity and cpp_parity.get('status')=='PASS' else 'UNVERIFIED',
        'evidence':{'mujoco':parity['job_id'] if parity else None,'cpp':cpp['job_id'] if cpp else None,'cpp_result':cpp_parity},
        'gap':'只覆盖桌面 TorchScript/ORT/C++ 实际后端；ARM 原生后端未执行'})
    rows.append({'level':'L2 输入输出契约','definition':'生产 C++ 的历史构造、344维编码和13维解码',
        'status':'VERIFIED' if cpp else 'UNVERIFIED','evidence':{'job_id':cpp['job_id'],'counts':cpp['result'].get('counts')} if cpp else None,
        'gap':'仅行走；踢球、完整 prepare/重置边界、多机器人探针和真机尚未覆盖'})
    rows.append({'level':'L3 调度控制语义','definition':'周期、PD/力矩、限幅、串并联与失效处理',
        'status':'UNVERIFIED','evidence':'bhuman/docs/policy-contract-v2.md + 有界仿真日志',
        'gap':'部分已有代码/仿真证据；真实 DDS 频率、deadline 和执行器转换未验证'})
    arm,bundle=proof('arm_build'),proof('bundle_offline')
    rows.append({'level':'L4 离线目标构建','definition':'真实 ARM64 ELF 与独立可核验离线产物',
        'status':'VERIFIED' if arm and bundle else 'UNVERIFIED',
        'evidence':{'arm_job':arm['job_id'] if arm else None,'bundle_job':bundle['job_id'] if bundle else None},
        'gap':'仅静态架构、依赖闭包和包完整性；不认证目标系统/固件运行兼容'})
    rows.append({'level':'L5 真机闭环','definition':'实机闭环与物理表现', 'status':'UNVERIFIED',
        'evidence':None,'gap':'当前不连接机器人；需要后续实物验证，不能从 L0-L4 推导'})
    return {'generated_at':util.now_local(),'rows':rows,'robot_connected':False}
