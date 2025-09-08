"""Synthetic probability model for testing."""

import numpy as np


def calibrated_sample(n: int = 100, probs=(0.7, 0.2, 0.1), seed: int | None = 0):
    """Generate labels and calibrated probability predictions.

    Parameters
    ----------
    n : int, optional
        Number of samples to generate, by default 100.
    probs : tuple, optional
        Underlying probability distribution for classes. Must sum to 1.
    seed : int | None, optional
        Seed for the random number generator, by default 0.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        Array of integer labels and array of probability distributions per sample.
    """
    rng = np.random.default_rng(seed)
    probs_arr = np.tile(probs, (n, 1))
    labels = rng.choice(len(probs), size=n, p=probs)
    return labels, probs_arr
