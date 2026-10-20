"""Compare actual MuJoCo actor outputs with TorchScript and official competition ONNX."""
from pathlib import Path
import argparse,hashlib,json,sys
import numpy as np
import torch
import onnxruntime as ort

BASE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--export-dir',type=Path,required=True)
    a=parser.parse_args();run=a.run.resolve()
    launch=json.loads((run/'launch.json').read_text())
    exported=json.loads((a.export_dir/'K1_actor_manifest.json').read_text())
    assert exported['checkpoint_sha256']==launch['checkpoint_sha256'], 'Export is from a different policy'
    scripted_path=a.export_dir/'K1_actor.pt'
    assert sha(scripted_path)==exported['torchscript']['sha256']
    x=np.load(run/'observations.npy',allow_pickle=False)
    with np.load(run/'trajectory.npz',allow_pickle=False) as f:actual=f['actions']
    assert x.ndim==2 and x.shape[1]==344 and actual.shape==(len(x),13) and len(x)>0
    assert np.isfinite(x).all() and np.isfinite(actual).all()
    torch.set_num_threads(1)
    scripted=torch.jit.load(str(scripted_path),map_location='cpu').eval()
    with torch.inference_mode():script=scripted(torch.from_numpy(x)).numpy()
    onnx=BASE.parent/'BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx'
    options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(onnx),sess_options=options,providers=['CPUExecutionProvider'])
    inp=session.get_inputs()[0]
    if len(inp.shape)==1:
        predicted=np.stack([np.asarray(session.run(None,{inp.name:row})[0]).reshape(13) for row in x])
    elif isinstance(inp.shape[0],int) and inp.shape[0]==1:
        predicted=np.concatenate([session.run(None,{inp.name:row[None,:]})[0].reshape(1,13) for row in x])
    else:predicted=session.run(None,{inp.name:x})[0]
    tolerance=1e-5+1e-4*np.abs(actual)
    results={}
    for name,y in [('torchscript',script),('official_competition_onnx',predicted)]:
        error=np.abs(actual-y)
        results[name]={'pass':bool(np.isfinite(y).all() and np.all(error<=tolerance)),
                       'maximum_absolute_error':float(error.max()),'mean_absolute_error':float(error.mean())}
    result={'status':'PASS' if all(r['pass'] for r in results.values()) else 'FAIL',
            'observations':len(x),'input_dim':344,'output_dim':13,'atol':1e-5,'rtol':1e-4,
            'results':results,'official_onnx_sha256':sha(onnx),'torchscript_sha256':sha(scripted_path),
            'checkpoint_sha256':launch['checkpoint_sha256'],'note':'MuJoCo Torch 2.11 outputs vs TorchScript/ORT in the existing Python 3.8 environment; no CompiledNN or robot claim.'}
    (run/'policy-parity.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='PASS' else 3
if __name__=='__main__':sys.exit(main())
