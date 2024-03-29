import warnings
from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
from autodp.autodp_core import Mechanism

from dp_learning_ff.ext.coinpress import algos
from dp_learning_ff.mechanisms import (
    CoinpressGM,
    ScaledCoinpressGM,
    calibrate_single_param,
)


@dataclass
class CoinpressPrototyping:
    _epsilon: Optional[float] = None
    _delta: Optional[float] = None
    _steps: Optional[int] = None
    _dist: Optional[str] = None
    Ps: Optional[Iterable[float]] = None
    _p_sampling: float = 1
    sample_each_step: bool = False
    seed: int = 42
    _order: float = 1
    calibrated: bool = False
    verbose: bool = False
    _mechanism: Mechanism = None

    def __post_init__(self):
        if self.calibrated:
            self.mechanism = CoinpressGM(
                self.Ps, self.p_sampling, self.sample_each_step
            )

    def prototypes(
        self, train_preds, train_targets, overwrite_seed: Optional[int] = None
    ):
        if self.mechanism is None:
            raise ValueError("Mechanism not calibrated")
        seed = self.seed if overwrite_seed is None else overwrite_seed
        return give_private_prototypes(
            train_preds,
            train_targets,
            self.mechanism.params["Ps"],
            seed=seed,
            subsampling=self.p_sampling,
            sample_each_step=self.sample_each_step,
            poisson_sampling=True,
        )

    @property
    def mechanism(self):
        return self._mechanism

    @mechanism.setter
    def mechanism(self, value):
        if hasattr(self, "_mechanism"):
            if self._mechanism is not None:
                warnings.warn("Overwriting existing mechanism")
        self._mechanism = value

    @property
    def epsilon(self):
        return self._epsilon

    @epsilon.setter
    def epsilon(self, value):
        print(value)
        assert (
            (value > 0) if value is not None else True
        ), f"epsilon must be positive, but received {value}"
        self._epsilon = value

    @property
    def delta(self):
        return self._delta

    @delta.setter
    def delta(self, value):
        assert (value > 0) if value is not None else True, "delta must be positive"
        self._delta = value

    @property
    def dist(self):
        return self._dist

    @dist.setter
    def dist(self, value):
        assert value in [
            "lin",
            "exp",
            "log",
            "eq",
            None,
        ], "dist must be in ['lin', 'exp', 'log', 'eq']"
        self._dist = value

    @property
    def order(self):
        return self._order

    @order.setter
    def order(self, value):
        self._order = value

    @property
    def steps(self):
        return self._steps

    @steps.setter
    def steps(self, value):
        assert (value > 0) if value is not None else True, "steps must be positive"
        self._steps = value

    @property
    def p_sampling(self):
        return self._p_sampling

    @p_sampling.setter
    def p_sampling(self, value):
        assert (
            (value > 0 and value <= 1) if value is not None else True
        ), "p_sampling must be in (0, 1]"
        self._p_sampling = value

    def try_calibrate(self):
        attrs1 = ["_epsilon", "_delta"]
        attrs2 = ["_dist", "_order", "_steps"]
        for attr in attrs1:
            if not hasattr(self, attr) or getattr(self, attr) is None:
                return
        if self.Ps is not None:  # overwrites attrs2
            return self.calibrate_Ps()
        for attr in attrs2:
            if getattr(self, attr) is None:
                return
        return self.calibrate_steps()

    def calibrate_steps(self):
        print(
            "Calibrating mechanism to epsilon={}, delta={}, dist={}, order={}, steps={}".format(
                self.epsilon, self.delta, self.dist, self.order, self.steps
            )
        )

        def scaled_mechanism(scale):
            return ScaledCoinpressGM(
                scale=scale,
                steps=self.steps,
                dist=self.dist,
                ord=self.order,
                p_sampling=self.p_sampling,
                sample_each_step=self.sample_each_step,
                name="ScaledCoinpressGM",
            )

        calibrated_mechanism = calibrate_single_param(
            scaled_mechanism, self.epsilon, self.delta, verbose=self.verbose
        )
        epsilon = calibrated_mechanism.get_approxDP(self.delta)
        print(
            "Calibrated mechanism with epsilon={}, scale={}, params={},".format(
                epsilon, calibrated_mechanism.scale, calibrated_mechanism.params
            )
        )
        self.mechanism = calibrated_mechanism

    def calibrate_Ps(self):
        print(
            "Calibrating mechanism to epsilon={}, delta={}, Ps={}".format(
                self.epsilon, self.delta, self.Ps
            )
        )

        def scaled_mechanism(scale):
            return ScaledCoinpressGM(
                scale=scale,
                Ps=self.Ps,
                p_sampling=self.p_sampling,
                sample_each_step=self.sample_each_step,
                name="ScaledCoinpressGM",
            )

        calibrated_mechanism = calibrate_single_param(
            scaled_mechanism, self.epsilon, self.delta, verbose=self.verbose
        )
        epsilon = calibrated_mechanism.get_approxDP(self.delta)
        print(
            "Calibrated mechanism with  epsilon={}, scale={}, params={},".format(
                epsilon, calibrated_mechanism.scale, calibrated_mechanism.params
            )
        )
        self.mechanism = calibrated_mechanism


def give_private_prototypes(
    train_preds: np.ndarray,
    train_targets: np.ndarray,
    Ps: np.ndarray,
    seed: int = 42,
    subsampling: float = 1.0,
    sample_each_step: bool = False,
    poisson_sampling: bool = True,
):
    """Returns a private prototype for each class.

    Args:
        train_preds (np.ndarray): (n, d)-array containing the predictions of the training set.
        train_targets (np.ndarray): (n, )-array containing the labels of the training set.
        Ps (np.ndarray): Array of privacy budget per step in (0,rho)-zCDP. To total privacy cost is the sum of this array. The algorithm will perform len(Ps) steps.
        seed (int): RNG seed
        subsampling (float): Ratio in (0, 1] of samples to use



    Returns:
        np.ndarray: (k, d)-array containing the private prototypes for each class.
    """
    if sample_each_step:
        raise NotImplementedError("Sampling each step is not implemented")
    targets = np.unique(train_targets)
    train_preds_sorted = [
        train_preds[train_targets == target].copy() for target in targets
    ]
    if subsampling < 1.0:
        rng = np.random.default_rng(seed)
        subsampled = []
        for M_x in train_preds_sorted:
            if poisson_sampling:
                occurences = rng.poisson(lam=subsampling, size=M_x.shape[0])
                subsampled_indices = np.arange(M_x.shape[0]).repeat(occurences)
                subsampled.append(M_x[subsampled_indices])
            else:
                rng.shuffle(M_x, axis=0)
                subsampled.append(M_x[: int(subsampling * M_x.shape[0])])
        train_preds_sorted = subsampled
    protos = np.asarray(
        [private_mean(train_preds_sorted[i], Ps) for i, target in enumerate(targets)]
    )
    return protos


def private_mean(X, Ps, r=None, c=None):
    if len(X.shape) != 2:
        raise ValueError("X must be a 2D array, but received shape: {}".format(X.shape))
    d = X.shape[1]
    if r is None:
        r = np.sqrt(d) * 3
    if c is None:
        c = np.zeros(d)
    t = len(Ps)
    mean = algos.multivariate_mean_iterative(X, c=c, r=r, t=t, Ps=Ps)
    return mean
