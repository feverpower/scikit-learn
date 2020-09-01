import numpy as np
from sklearn.datasets import make_regression
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score
import pytest

from sklearn.ensemble._hist_gradient_boosting.binning import _BinMapper
from sklearn.ensemble._hist_gradient_boosting.grower import TreeGrower
from sklearn.ensemble._hist_gradient_boosting._predictor import TreePredictor
from sklearn.ensemble._hist_gradient_boosting.common import (
    G_H_DTYPE, ALMOST_INF)


@pytest.mark.parametrize('n_bins', [200, 256])
def test_regression_dataset(n_bins):
    X, y = make_regression(n_samples=500, n_features=10, n_informative=5,
                           random_state=42)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, random_state=42)

    mapper = _BinMapper(n_bins=n_bins, random_state=42)
    X_train_binned = mapper.fit_transform(X_train)

    # Init gradients and hessians to that of least squares loss
    gradients = -y_train.astype(G_H_DTYPE)
    hessians = np.ones(1, dtype=G_H_DTYPE)

    min_samples_leaf = 10
    max_leaf_nodes = 30
    grower = TreeGrower(X_train_binned, gradients, hessians,
                        min_samples_leaf=min_samples_leaf,
                        max_leaf_nodes=max_leaf_nodes, n_bins=n_bins,
                        n_bins_non_missing=mapper.n_bins_non_missing_)
    grower.grow()

    predictor = grower.make_predictor(num_thresholds=mapper.bin_thresholds_)

    assert r2_score(y_train, predictor.predict(X_train)) > 0.82
    assert r2_score(y_test, predictor.predict(X_test)) > 0.67


@pytest.mark.parametrize('num_threshold, expected_predictions', [
    (-np.inf, [0, 1, 1, 1]),
    (10, [0, 0, 1, 1]),
    (20, [0, 0, 0, 1]),
    (ALMOST_INF, [0, 0, 0, 1]),
    (np.inf, [0, 0, 0, 0]),
])
def test_infinite_values_and_thresholds(num_threshold, expected_predictions):
    # Make sure infinite values and infinite thresholds are handled properly.
    # In particular, if a value is +inf and the threshold is ALMOST_INF the
    # sample should go to the right child. If the threshold is inf (split on
    # nan), the +inf sample will go to the left child.

    X = np.array([-np.inf, 10, 20,  np.inf]).reshape(-1, 1)
    predictor = TreePredictor(3)

    # We just construct a simple tree with 1 root and 2 children
    # parent node
    predictor._set_node(0, left=1, right=2, feature_idx=0,
                        num_threshold=num_threshold)
    # left child
    predictor._set_node(1, is_leaf=True, value=0)

    # right child
    predictor._set_node(2, is_leaf=True, value=1)

    predictions = predictor.predict(X)

    assert np.all(predictions == expected_predictions)
