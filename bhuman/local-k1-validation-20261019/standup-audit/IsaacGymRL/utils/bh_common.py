"""Reproducibility helpers for the isolated B-Human training adaptation.

Only tensors and Python primitives are stored: loading always uses
weights_only=True. Old v1 checkpoints using pickled NumPy RNG arrays are
preserved, but never silently loaded through unrestricted pickle.
"""
import argparse
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch

CKPT_FORMAT = "bh-k1-ckpt-v2"
SOURCE_ID = "bhuman/MachineLearning@c3fed817e6e8fd06418bea824b1f1ab0157379d2"


def str2bool(value):
    if isinstance(value, bool):
        return value
    value = str(value).lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise argparse.ArgumentTypeError("expected true/false or 1/0")


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def source_hash():
    root = Path(__file__).resolve().parents[1]
    files = sorted(p for p in root.rglob("*") if p.suffix in (".py", ".yaml") and "logs" not in p.parts)
    digest = hashlib.sha256()
    for p in files:
        digest.update(str(p.relative_to(root)).encode())
        digest.update(p.read_bytes())
    return digest.hexdigest()


def config_contract(cfg):
    # Runtime bookkeeping can vary between sessions. Algorithm, assets,
    # rewards, physics and observation configuration must remain identical.
    contract = {k: v for k, v in cfg.items() if k not in ("basic", "viewer", "runner")}
    contract["runner"] = {k: v for k, v in cfg.get("runner", {}).items() if k not in ("save_interval", "use_wandb")}
    contract["task"] = cfg.get("basic", {}).get("task")
    return hashlib.sha256(json.dumps(contract, sort_keys=True, allow_nan=False).encode()).hexdigest()


def assert_tree_equal(a, b, path="state"):
    if isinstance(a, torch.Tensor):
        if not isinstance(b, torch.Tensor) or not torch.equal(a.cpu(), b.cpu()):
            raise ValueError("restored tensor differs: " + path)
    elif isinstance(a, dict):
        if not isinstance(b, dict) or a.keys() != b.keys():
            raise ValueError("restored keys differ: " + path)
        for k in a:
            assert_tree_equal(a[k], b[k], path + "." + str(k))
    elif isinstance(a, (tuple, list)):
        if type(a) != type(b) or len(a) != len(b):
            raise ValueError("restored sequence differs: " + path)
        for i, (x, y) in enumerate(zip(a, b)):
            assert_tree_equal(x, y, path + "." + str(i))
    elif a != b:
        raise ValueError("restored value differs: " + path)


def rng_snapshot():
    name, keys, position, has_gauss, cached_gauss = np.random.get_state()
    snap = {"torch": torch.get_rng_state(), "python": random.getstate(),
            "numpy": [name, keys.tolist(), int(position), int(has_gauss), float(cached_gauss)]}
    if torch.cuda.is_initialized():
        snap["cuda"] = torch.cuda.get_rng_state_all()
    return snap


def restore_rng(snap):
    torch.set_rng_state(snap["torch"].cpu())
    name, keys, pos, has_gauss, cached = snap["numpy"]
    np.random.set_state((name, np.asarray(keys, dtype=np.uint32), pos, has_gauss, cached))
    random.setstate(snap["python"])
    if snap.get("cuda"):
        torch.cuda.set_rng_state_all([state.cpu() for state in snap["cuda"]])


def load_checkpoint(model, optimizer, path, mode, device="cpu", cfg=None):
    if mode not in ("actor", "warm-start", "full"):
        raise ValueError("unknown checkpoint load mode: " + mode)
    print("[load] checkpoint=%s mode=%s" % (path, mode))
    # CPU map preserves CPU RNG state type, even when the model is on CUDA.
    sd = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(sd, dict) or "model" not in sd:
        raise ValueError("not a state_dict checkpoint; use torchscript mode for .pt actors")
    mstate = sd["model"]
    actor = {k[len("actor."):]: v for k, v in mstate.items() if k.startswith("actor.")}
    ref_actor = model.actor.state_dict()
    if actor.keys() != ref_actor.keys():
        raise ValueError("actor keys do not match")
    for k, v in actor.items():
        if v.shape != ref_actor[k].shape or not torch.isfinite(v).all():
            raise ValueError("invalid actor tensor: " + k)
    info = {"path": os.path.abspath(path), "sha256": file_hash(path), "mode": mode,
            "format": sd.get("format", "upstream"), "iteration": sd.get("iteration"),
            "env_steps": sd.get("env_steps"), "lr": sd.get("lr"), "rng_restored": False}
    if mode != "full":
        model.actor.load_state_dict(actor, strict=True)
        print("[load] actor strictly loaded; critic, logstd and optimizer retain fresh initialization")
        return info
    if sd.get("format") != CKPT_FORMAT or optimizer is None or cfg is None:
        raise ValueError("full resume requires a v2 checkpoint, optimizer, and effective config")
    for k in ("optimizer", "rng", "iteration", "env_steps", "lr", "config_contract", "adaptation_sha256"):
        if k not in sd:
            raise ValueError("resume checkpoint missing " + k)
    if sd["config_contract"] != config_contract(cfg):
        raise ValueError("resume configuration differs in training semantics")
    source_matches = sd["adaptation_sha256"] == source_hash()
    if not source_matches:
        print("[load] SOURCE CHANGE: state compatibility verified below; recipe continuity is not certified")
    for k, v in mstate.items():
        if not torch.isfinite(v).all():
            raise ValueError("non-finite checkpoint parameter: " + k)
    model.load_state_dict(mstate, strict=True)
    optimizer.load_state_dict(sd["optimizer"])
    assert_tree_equal(mstate, model.state_dict(), "model")
    assert_tree_equal(sd["optimizer"], optimizer.state_dict(), "optimizer")
    if any(group["lr"] != sd["lr"] for group in optimizer.param_groups):
        raise ValueError("checkpoint learning rate differs from optimizer")
    restore_rng(sd["rng"])
    assert_tree_equal(sd["rng"], rng_snapshot(), "rng")
    info.update(rng_restored=True, state_equality_verified=True, source_matches=source_matches,
                checkpoint_source_sha256=sd["adaptation_sha256"], current_source_sha256=source_hash(),
                environment_state_restored=False)
    print("[load] model/optimizer/RNG equality verified; environment will reset")
    return info


def save_checkpoint_v2(recorder, model, optimizer, iteration, env_steps, lr, cfg, tag, extra=None):
    payload = {"format": CKPT_FORMAT, "source_id": SOURCE_ID,
               "adaptation_sha256": source_hash(), "config_contract": config_contract(cfg),
               "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "iteration": int(iteration), "env_steps": int(env_steps), "lr": float(lr),
               "model": model.state_dict(), "optimizer": optimizer.state_dict(),
               "rng": rng_snapshot(), "config": cfg,
               "not_serialized": ["PhysX internal state", "per-environment reset/terrain/curriculum state",
                                  "rollout buffer; resumed session begins with env.reset()"]}
    if extra:
        payload.update(extra)
    recorder.save(payload, tag)
    return payload


def guard_finite(model, scalars, diag_path):
    """Raise SystemExit(2) after dumping diagnostics if anything is non-finite.

    Replaces the upstream reset_logstd NaN branch: we fail loudly, keep the
    last valid checkpoint untouched (this guard runs before any save) and
    never silently zero out NaNs.
    """
    bad = []
    for k, v in scalars.items():
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(f):
            bad.append("scalar:%s=%s" % (k, f))
    with torch.no_grad():
        for k, p in model.named_parameters():
            if not torch.isfinite(p).all():
                bad.append("param:%s" % k)
            if p.grad is not None and not torch.isfinite(p.grad).all():
                bad.append("grad:%s" % k)
    if not bad:
        return
    diag = {
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bad": bad[:200],
        "n_bad": len(bad),
        "scalars": {k: (float(v) if v is not None else None) for k, v in scalars.items()},
        "logstd": model.logstd.detach().cpu().flatten().tolist(),
        "hint": "non-finite state detected; training halted before checkpoint overwrite",
    }
    os.makedirs(os.path.dirname(diag_path), exist_ok=True)
    with open(diag_path, "w") as f:
        json.dump(diag, f, indent=2)
    print("[guard_finite] NON-FINITE STATE detected -> %s" % diag_path, file=sys.stderr)
    print("[guard_finite] first issues: %s" % bad[:10], file=sys.stderr)
    sys.exit(2)
