"""A/B baseline: no estimator. Official walk 344 is copied as-is."""
from __future__ import annotations

from interface import EstimatorInterface, register


class PassthroughEstimator(EstimatorInterface):
    name = "passthrough"
    family = "passthrough"
    latent_dim = 0

    def encode_latent(self, flat_344) -> list[float]:
        self.actor_observation(flat_344)
        return []


register("passthrough", PassthroughEstimator)
