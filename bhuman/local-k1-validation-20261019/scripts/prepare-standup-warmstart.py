"""Extract a verified actor-only warm start; never claim a full training resume."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--observations', type=Path)
    args = parser.parse_args()
    root = args.source_root.resolve()
    source = root / 'pre-trained/GetUp/K1_stand_up.pt'
    output = args.output.resolve()
    if output.exists() or output.with_suffix('.json').exists():
        parser.error('output already exists; choose a new versioned path')
    sys.path.insert(0, str(root))
    from utils.model import ActorCritic
    from utils.bh_common import load_checkpoint, assert_tree_equal

    torch.manual_seed(17)
    reference = torch.jit.load(str(source), map_location='cpu').eval()
    model = ActorCritic(22, 73, 38).eval()
    actor = reference.state_dict()
    expected = model.actor.state_dict()
    if actor.keys() != expected.keys():
        raise ValueError('TorchScript and trainable actor parameter names differ')
    for name, tensor in actor.items():
        if tensor.shape != expected[name].shape or not torch.isfinite(tensor).all():
            raise ValueError('invalid actor tensor ' + name)
    model.actor.load_state_dict(actor, strict=True)
    batches = [torch.zeros(1, 73), torch.randn(1024, 73), torch.randn(1024, 73) * 3]
    observations_hash = None
    if args.observations:
        observation_array = np.load(str(args.observations), allow_pickle=False)
        if observation_array.shape[-1] != 73:
            raise ValueError('recorded observation contract is not 73 inputs')
        batches.append(torch.from_numpy(observation_array.reshape(-1, 73)).float())
        observations_hash = digest(args.observations)
    errors = []
    with torch.no_grad():
        for batch in batches:
            wanted, actual = reference(batch), model.actor(batch)
            if not torch.isfinite(wanted).all() or not torch.isfinite(actual).all():
                raise ValueError('nonfinite actor output')
            error = float((wanted-actual).abs().max())
            if error > 1e-6:
                raise ValueError('TorchScript/actor functional mismatch: ' + str(error))
            errors.append(error)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {'format':'bhuman_actor_warmstart_v1',
               'model':{'actor.'+name:tensor.cpu().clone() for name,tensor in actor.items()},
               'source_sha256':digest(source), 'task':'K1_Stand_Up',
               'contract':{'observations':73,'actions':22},
               'not_present':['critic','optimizer','RNG','training iteration','PhysX state']}
    torch.save(payload, str(output))
    restored = ActorCritic(22, 73, 38)
    critic_before = {k:v.detach().clone() for k,v in restored.critic.state_dict().items()}
    info = load_checkpoint(restored, None, str(output), 'warm-start')
    assert_tree_equal(critic_before, restored.critic.state_dict(), 'critic unchanged')
    assert_tree_equal(actor, restored.actor.state_dict(), 'actor restored')
    assert torch.equal(restored.logstd.detach(), torch.full((1,22), -2.0))
    report = {'source':str(source),'source_sha256':digest(source),'output':str(output),
              'output_sha256':digest(output),'actor_shapes':{k:list(v.shape) for k,v in actor.items()},
              'max_abs_error':max(errors),'evaluated_observations':sum(len(b) for b in batches),
              'recorded_observations_sha256':observations_hash,
              'critic_and_logstd_fresh':True,'load_info':info,
              'meaning':'Actor-only warm start. Training critic, logstd and optimizer are newly initialized; no original training state is recovered.'}
    output.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
