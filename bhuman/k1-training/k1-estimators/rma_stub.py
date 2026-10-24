"""RMA-style bypass stub (Kumar et al., RSS 2021, arXiv:2107.04034).

A real RMA adaptation module would encode walk history into extras for
the critic / a privileged reconstructor. This file only reserves the
name and keeps actor I/O at 344->13.
"""
from __future__ import annotations

from interface import ESTIMATOR_LATENT, EstimatorInterface, register, split_walk_obs


class RMAEstimator(EstimatorInterface):
    name = "rma"
    family = "rma"
    latent_dim = ESTIMATOR_LATENT

    def encode_latent(self, flat_344) -> list[float]:
        frames, _tail = split_walk_obs(flat_344)
        if len(frames) != 10:
            raise AssertionError("RMA stub lost the 10-frame walk history")
        # Zeros: do not invent a trained encoder. History is validated only.
        return [0.0] * self.latent_dim


register("rma", RMAEstimator)
