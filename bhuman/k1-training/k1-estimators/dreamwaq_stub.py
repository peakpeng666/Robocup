"""DreamWaQ-style bypass stub (arXiv:2301.10602 / 2409.19709).

Implicit-terrain / multimodal extras stay off the actor vector. Official
walk remains 344->13. This is the P1 single-factor counterpart to RMA.
"""
from __future__ import annotations

from interface import ESTIMATOR_LATENT, EstimatorInterface, register, split_walk_obs


class DreamWaQEstimator(EstimatorInterface):
    name = "dreamwaq"
    family = "dreamwaq"
    latent_dim = ESTIMATOR_LATENT

    def encode_latent(self, flat_344) -> list[float]:
        _frames, tail = split_walk_obs(flat_344)
        if len(tail) != 24:
            raise AssertionError("DreamWaQ stub lost the 24-D walk tail")
        return [0.0] * self.latent_dim


register("dreamwaq", DreamWaQEstimator)
