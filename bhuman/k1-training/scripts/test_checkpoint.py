"""CPU tests for public actor compatibility and safe, verifiable v2 resume."""
import copy
import json
import os
from pathlib import Path
import random
import sys
import tempfile
from unittest.mock import patch

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/IsaacGymRL"))
from utils.model import ActorCritic
from utils.bh_common import load_checkpoint, save_checkpoint_v2, assert_tree_equal, str2bool


def main():
    torch.manual_seed(7)
    model = ActorCritic(13, 344, 16)
    critic_before = copy.deepcopy(model.critic.state_dict())
    public = ROOT / "src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth"
    sd = torch.load(public, map_location="cpu", weights_only=True)
    assert sd["model"]["critic.0.weight"].shape == (256, 359)
    load_checkpoint(model, None, public, "actor")
    assert_tree_equal(critic_before, model.critic.state_dict())
    assert torch.equal(model.logstd, torch.full((1, 13), -2.0))
    assert str2bool("false") is False and str2bool("0") is False

    with tempfile.TemporaryDirectory(dir=ROOT / "cache/tmp") as temporary:
        path = Path(temporary) / "checkpoint.pth"

        class Recorder:
            def save(self, payload, tag):
                torch.save(payload, path)

        cfg = {"basic": {"task": "unit"}, "algorithm": {"gamma": .98}, "env": {"num_envs": 2}}
        model = ActorCritic(2, 3, 1)
        opt = torch.optim.Adam(model.parameters(), lr=.001)
        loss = model.actor(torch.ones(2, 3)).square().mean()
        loss.backward()
        opt.step()
        save_checkpoint_v2(Recorder(), model, opt, 5, 7680, .001, cfg, "final")
        checkpoint = torch.load(path, weights_only=True, map_location="cpu")
        expected = (random.random(), np.random.rand(), torch.rand(2))
        restored = ActorCritic(2, 3, 1)
        restored_opt = torch.optim.Adam(restored.parameters())
        info = load_checkpoint(restored, restored_opt, path, "full", cfg=cfg)
        actual = (random.random(), np.random.rand(), torch.rand(2))
        assert expected[:2] == actual[:2] and torch.equal(expected[2], actual[2])
        assert info["env_steps"] == 7680 and info["iteration"] == 5
        assert_tree_equal(checkpoint["model"], restored.state_dict())
        assert_tree_equal(checkpoint["optimizer"], restored_opt.state_dict())
        checkpoint["adaptation_sha256"] = "reviewed-previous-source"
        torch.save(checkpoint, path)
        changed = load_checkpoint(restored, restored_opt, path, "full", cfg=cfg)
        assert changed["source_matches"] is False and changed["state_equality_verified"]
        bad_cfg = copy.deepcopy(cfg)
        bad_cfg["algorithm"]["gamma"] = .9
        try:
            load_checkpoint(restored, restored_opt, path, "full", cfg=bad_cfg)
        except ValueError:
            pass
        else:
            raise AssertionError("incompatible training config accepted")
        # A failed restricted read must propagate without any unsafe retry.
        with patch("torch.load", side_effect=RuntimeError("restricted read failed")) as mocked:
            try:
                load_checkpoint(restored, None, path, "actor")
            except RuntimeError:
                pass
            assert mocked.call_count == 1
            assert mocked.call_args.kwargs["weights_only"] is True
        # A policy LR controller must not overwrite an independent critic LR
        # on save/load. Both groups, moments, and their order are preserved.
        def split_optimizer(m):
            return torch.optim.Adam([
                {'params':list(m.actor.parameters()) + [m.logstd], 'name':'policy', 'lr':.001},
                {'params':m.critic.parameters(), 'name':'critic', 'lr':.0003}])
        split = ActorCritic(2,3,1)
        split_opt = split_optimizer(split)
        (split.actor(torch.ones(2,3)).square().mean() + split.est_value(torch.ones(2,3), torch.ones(2,1)).square().mean()).backward()
        split_opt.step()
        save_checkpoint_v2(Recorder(), split, split_opt, 8, 100, .001, cfg, 'final')
        split_restored = ActorCritic(2,3,1)
        split_restored_opt = split_optimizer(split_restored)
        load_checkpoint(split_restored, split_restored_opt, path, 'full', cfg=cfg)
        assert_tree_equal(split_opt.state_dict(), split_restored_opt.state_dict())
        assert [g['lr'] for g in split_restored_opt.param_groups] == [.001,.0003]
    print(json.dumps({"public_actor_strict": "PASS", "critic_preserved": "PASS",
                      "v2_weights_only": "PASS", "model_optimizer_rng_equality": "PASS",
                      "config_rejection": "PASS", "no_unsafe_fallback": "PASS", "separate_group_lr_resume":"PASS"}))


if __name__ == "__main__":
    main()
