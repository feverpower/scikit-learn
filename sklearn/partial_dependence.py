"""Partial dependence plots for regression and classification models."""

# Authors: Peter Prettenhofer
#          Trevor Stephens
# License: BSD 3 clause

from itertools import count
import numbers

import numpy as np
from scipy.stats.mstats import mquantiles

from .base import is_classifier, is_regressor
from .utils.extmath import cartesian
from .externals.joblib import Parallel, delayed
from .externals import six
from .externals.six.moves import map, range, zip
from .utils import check_array
from .utils.validation import check_is_fitted
from .tree._tree import DTYPE
from .exceptions import NotFittedError


__all__ = ['partial_dependence', 'plot_partial_dependence']


def _grid_from_X(X, percentiles=(0.05, 0.95), grid_resolution=100):
    """Generate a grid of points based on the ``percentiles of ``X``.

    The grid is generated by placing ``grid_resolution`` equally
    spaced points between the ``percentiles`` of each column
    of ``X``. If ``grid_resolution`` is bigger than the number of unique values
    in a column, then those unique values will be used instead.

    Parameters
    ----------
    X : ndarray
        The data
    percentiles : tuple of floats
        The percentiles which are used to construct the extreme
        values of the grid axes.
    grid_resolution : int
        The number of equally spaced points to be placed on the grid for a
        given feature.

    Returns
    -------
    grid : ndarray
        All data points on the grid. This is the cartesian product of ``axes``.
    axes : list of ndarray
        The axes with which the grid has been created. The ndarrays may be of
        different shape: either (grid_resolution, ) or (n_unique_values,).
    """
    try:
        assert len(percentiles) == 2
    except (AssertionError, TypeError):
        raise ValueError('percentiles must be a sequence of 2 elements.')
    if not all(0. <= x <= 1. for x in percentiles):
        raise ValueError('percentiles values must be in [0, 1].')
    if percentiles[0] > percentiles[1]:
        raise ValueError('percentiles[0] must be less than percentiles[1].')

    axes = []
    for feature in range(X.shape[1]):
        uniques = np.unique(X[:, feature])
        if uniques.shape[0] < grid_resolution:
            # feature has low resolution use unique vals
            axis = uniques
        else:
            # create axis based on percentiles and grid resolution
            emp_percentiles = mquantiles(X, prob=percentiles, axis=0)
            axis = np.linspace(emp_percentiles[0, feature],
                               emp_percentiles[1, feature],
                               num=grid_resolution, endpoint=True)
        axes.append(axis)

    return cartesian(axes), axes


def _partial_dependence_recursion(est, grid, target_variables, X=None):
    # TODO: The pattern below required to avoid a namespace collision.
    # TODO: Move below imports to module level import at 0.22 release.
    from .ensemble._gradient_boosting import _partial_dependence_tree
    from .ensemble.gradient_boosting import BaseGradientBoosting

    # grid needs to be DTYPE
    grid = np.asarray(grid, dtype=DTYPE, order='C')

    if isinstance(est, BaseGradientBoosting):
        n_trees_per_stage = est.estimators_.shape[1]
        n_estimators = est.estimators_.shape[0]
        learning_rate = est.learning_rate
    else:
        n_trees_per_stage = 1
        n_estimators = len(est.estimators_)
        learning_rate = 1.
    pdp = np.zeros((n_trees_per_stage, grid.shape[0]), dtype=np.float64,
                   order='C')
    for stage in range(n_estimators):
        for k in range(n_trees_per_stage):
            if isinstance(est, BaseGradientBoosting):
                tree = est.estimators_[stage, k].tree_
            else:
                tree = est.estimators_[stage].tree_
            _partial_dependence_tree(tree, grid, target_variables,
                                     learning_rate, pdp[k])

    # _partial_dependence_tree doesn't add the initial estimator to the
    # predictions so we do it here
    if isinstance(est, BaseGradientBoosting):
        pdp += est._init_decision_function(X).mean()
    
    print(pdp.shape)

    return pdp


def _partial_dependence_brute(est, grid, target_variables, X):

    pdp = []
    for new_values in grid:
        X_eval = X.copy()
        for i, variable in enumerate(target_variables):
            X_eval[:, variable] = new_values[i]

        try:
            predictions = (est.predict(X_eval) if is_regressor(est)
                           else est.predict_proba(X_eval))
        except NotFittedError:
            raise ValueError('est parameter must be a fitted estimator')

        # Note: predictions is of shape
        # (n_points,) for non-multioutput regressors
        # (n_points, n_tasks) for multioutput regressors
        # (n_points, 1) for the regressors in cross_decomposition (I think)
        # (n_points, 2)  for binary classifaction
        # (n_points, n_classes) for multiclass classification

        # Commenting this out for now.
        # if is_classifier(est):
        #     predictions = np.log(np.clip(predictions, 1e-16, 1))
        #     # not sure yet why we need to center probas?
        #     predictions = predictions - np.mean(predictions, axis=1,
        #                                         keepdims=True)

        pdp.append(np.mean(predictions, axis=0))  # average over samples

    # reshape pdp to (n_targets, n_points) where n_targets is:
    # - 1 for non-multioutput regression and binary classification (shape is
    #   already correct in those cases)
    # - n_tasks for multi-output regression
    # - n_classes for multiclass classification.
    pdp = np.array(pdp).T
    if is_regressor(est) and pdp.ndim == 1:
        # non-multioutput regression, pdp shape is (n_points,)
        pdp = pdp.reshape(1, -1)
    elif is_classifier(est) and pdp.shape[0] == 2:
        # Binary classification, pdp shape is (2, n_points).
        pdp = pdp[1] # we output the effect of **positive** class
        pdp = pdp.reshape(1, -1)

    return pdp

def partial_dependence(est, target_variables, grid=None, X=None,
                       percentiles=(0.05, 0.95), grid_resolution=100,
                       method='auto'):
    """Partial dependence of ``target_variables``.

    Partial dependence plots show the dependence between the joint values
    of the ``target_variables`` and the function represented
    by the ``est``.

    Read more in the :ref:`User Guide <partial_dependence>`.

    Parameters
    ----------
    est : BaseEstimator
        A fitted classification or regression model.
    target_variables : array-like, dtype=int
        The target features for which the partial dependency should be
        computed (size should be smaller than 3 for visual renderings).
    grid : array-like, shape=(n_points, len(target_variables))
        The grid of ``target_variables`` values for which the
        partial dependency should be evaluated (either ``grid`` or ``X``
        must be specified).
    X : array-like, shape=(n_samples, n_features)
        The data on which ``est`` was trained. It is used to generate
        a ``grid`` for the ``target_variables``. The ``grid`` comprises
        ``grid_resolution`` equally spaced points between the two
        ``percentiles``.
    output : int, optional (default=None)
        The output index to use for multi-output estimators.
    percentiles : (low, high), default=(0.05, 0.95)
        The lower and upper percentile used to create the extreme values
        for the ``grid``. Only if ``X`` is not None.
    grid_resolution : int, default=100
        The number of equally spaced points on the ``grid``.
    method : {'recursion', 'brute', 'auto'}, default='auto'
        The method to use to calculate the partial dependence function:

        - If 'recursion', the underlying trees of ``est`` will be recursed to
          calculate the function. Only supported for BaseGradientBoosting.
        - If 'brute', the function will be calculated by calling the
          ``predict_proba`` method of ``est`` for classification or ``predict``
          for regression on ``X``for every point in the grid. To speed up this
          method, you can use a subset of ``X`` or a more coarse grid.
        - If 'auto', then 'recursion' will be used if ``est`` is
          BaseGradientBoosting, and 'brute' used for other
          estimators.

    Returns
    -------
    pdp : array, shape=(n_classes, n_points)
        The partial dependence function evaluated on the ``grid``.
        For regression and binary classification ``n_classes==1``.
    axes : seq of ndarray or None
        The axes with which the grid has been created or None if
        the grid has been given.

    Examples
    --------
    >>> samples = [[0, 0, 2], [1, 0, 0]]
    >>> labels = [0, 1]
    >>> from sklearn.ensemble import GradientBoostingClassifier
    >>> gb = GradientBoostingClassifier(random_state=0).fit(samples, labels)
    >>> kwargs = dict(X=samples, percentiles=(0, 1), grid_resolution=2)
    >>> partial_dependence(gb, [0], **kwargs) # doctest: +SKIP
    (array([[-4.52...,  4.52...]]), [array([ 0.,  1.])])
    """

    from .ensemble.gradient_boosting import BaseGradientBoosting

    if not (is_classifier(est) or is_regressor(est)):
        raise ValueError('est must be a fitted regressor or classifier.')

    if (hasattr(est, 'classes_') and
            isinstance(est.classes_[0], np.ndarray)):
        raise ValueError('Multiclass-multioutput estimators are not supported')

    if X is not None:
        X = check_array(X)

    if method == 'auto':
        if isinstance(est, BaseGradientBoosting):
            method = 'recursion'
        else:
            method = 'brute'
    method_to_function = {
        'brute': _partial_dependence_brute,
        'recursion': _partial_dependence_recursion
    }
    if method not in method_to_function:
        raise ValueError(
            'method {} is invalid. Accepted method names are {}, auto.'.format(
                method, ', '.join(method_to_function.keys())))

    if method == 'recursion':
        if not isinstance(est, BaseGradientBoosting):
            raise ValueError(
                'est must be an instance of BaseGradientBoosting '
                'for the "recursion" method. Try using method="brute".')
        check_is_fitted(est, 'estimators_',
                        msg='est parameter must be a fitted estimator')
        # Note: if method is brute, this check is done at prediction time
        n_features = est.n_features_
    elif X is None:
        raise ValueError('X is required for brute method')
    else:
        if is_classifier(est) and not hasattr(est, 'predict_proba'):
            raise ValueError('est requires a predict_proba() method for '
                             'method="brute" for classification.')
        n_features = X.shape[1]

    target_variables = np.asarray(target_variables, dtype=np.int32,
                                  order='C').ravel()
    if any(not (0 <= fx < n_features) for fx in target_variables):
        raise ValueError('all target_variables must be in [0, %d]'
                         % (n_features - 1))

    if (grid is None and X is None):
        raise ValueError('Either grid or X must be specified.')

    if grid is None:
        grid, axes = _grid_from_X(X[:, target_variables], percentiles,
                                  grid_resolution)
    else:
        grid = np.asarray(grid)
        axes = None  # don't return axes if grid is given
        # grid must be 2d
        if grid.ndim == 1:
            grid = grid[:, np.newaxis]
        if grid.ndim != 2:
            raise ValueError('grid must be 1d or 2d, got %dd dimensions' %
                             grid.ndim)
        if grid.shape[1] != target_variables.shape[0]:
            raise ValueError('grid.shape[1] ({}) must be equal to the number '
                             'of target variables ({})'.format(
                                 grid.shape[1], target_variables.shape[0]))

    pdp = method_to_function[method](est, grid, target_variables, X)

    return pdp, axes


def plot_partial_dependence(est, X, features, feature_names=None,
                            target=None, n_cols=3, grid_resolution=100,
                            percentiles=(0.05, 0.95), method='auto',
                            n_jobs=1, verbose=0, ax=None, line_kw=None,
                            contour_kw=None, **fig_kw):
    """Partial dependence plots for ``features``.

    The ``len(features)`` plots are arranged in a grid with ``n_cols``
    columns. Two-way partial dependence plots are plotted as contour
    plots.

    Read more in the :ref:`User Guide <partial_dependence>`.

    Parameters
    ----------
    est : BaseEstimator
        A fitted classification or regression model.
    X : array-like, shape=(n_samples, n_features)
        The data on which ``est`` was trained.
    features : seq of ints, strings, or tuples of ints or strings
        If seq[i] is an int or a tuple with one int value, a one-way
        PDP is created; if seq[i] is a tuple of two ints, a two-way
        PDP is created.
        If feature_names is specified and seq[i] is an int, seq[i]
        must be < len(feature_names).
        If seq[i] is a string, feature_names must be specified, and
        seq[i] must be in feature_names.
    feature_names : seq of str
        Name of each feature; feature_names[i] holds
        the name of the feature with index i.
    label : object
        The class label for which the PDPs should be computed.
        Only if est is a multi-class model. Must be in ``est.classes_``.
    output : int, optional (default=None)
        The output index to use for multi-output estimators.
    n_cols : int
        The number of columns in the grid plot (default: 3).
    grid_resolution : int, default=100
        The number of equally spaced points on the axes.
    percentiles : (low, high), default=(0.05, 0.95)
        The lower and upper percentile used to create the extreme values
        for the PDP axes.
    method : {'recursion', 'brute', 'auto'}, default='auto'
        The method to use to calculate the partial dependence function:

        - If 'recursion', the underlying trees of ``est`` will be recursed to
          calculate the function. Only supported for BaseGradientBoosting.
        - If 'brute', the function will be calculated by calling the
          ``predict_proba`` method of ``est`` for classification or ``predict``
          for regression on ``X``for every point in the grid. To speed up this
          method, you can use a subset of ``X`` or a more coarse grid.
        - If 'auto', then 'recursion' will be used if ``est`` is
          BaseGradientBoosting, and 'brute' used for other estimators.
    n_jobs : int
        The number of CPUs to use to compute the PDs. -1 means 'all CPUs'.
        Defaults to 1.
    verbose : int
        Verbose output during PD computations. Defaults to 0.
    ax : Matplotlib axis object, default None
        An axis object onto which the plots will be drawn.
    line_kw : dict
        Dict with keywords passed to the ``matplotlib.pyplot.plot`` call.
        For one-way partial dependence plots.
    contour_kw : dict
        Dict with keywords passed to the ``matplotlib.pyplot.plot`` call.
        For two-way partial dependence plots.
    **fig_kw : dict
        Dict with keywords passed to the figure() call.
        Note that all keywords not recognized above will be automatically
        included here.

    Returns
    -------
    fig : figure
        The Matplotlib Figure object.
    axs : seq of Axis objects
        A seq of Axis objects, one for each subplot.

    Examples
    --------
    >>> from sklearn.datasets import make_friedman1
    >>> from sklearn.ensemble import GradientBoostingRegressor
    >>> X, y = make_friedman1()
    >>> clf = GradientBoostingRegressor(n_estimators=10).fit(X, y)
    >>> fig, axs = plot_partial_dependence(clf, X, [0, (0, 1)]) #doctest: +SKIP
    ...
    """
    import matplotlib.pyplot as plt
    from matplotlib import transforms
    from matplotlib.ticker import MaxNLocator
    from matplotlib.ticker import ScalarFormatter
    # TODO: The pattern below required to avoid a namespace collision.
    # TODO: Move below imports to module level import at 0.22 release.
    from .ensemble.gradient_boosting import BaseGradientBoosting

    # set target_idx for multi-class estimators
    if hasattr(est, 'classes_') and np.size(est.classes_) > 2:
        if target is None:
            raise ValueError('target must be specified for multi-class PDP')
        target_idx = np.searchsorted(est.classes_, target)
        if est.classes_[target_idx] != target:
            raise ValueError('target %s not in ``est.classes_``' % str(target))
    else:
        # regression and binary classification
        target_idx = 0

    if is_regressor(est) and "MultiTask" in est.__class__.__name__:
        # multioutput regressor
        if target is None:
            raise ValueError(
                'target must be specified for multi-output regressors')
        if target < 0:
            raise ValueError('target must be in [0, n_tasks], got {}.'.format(
                target))
        # Note: for multitask, upper bound for target can only be checked once
        # we have the predictions
        target_idx = target
    else:
        target_idx = 0

    #TODO: DYPE?????
    X = check_array(X, dtype=DTYPE, order='C')
    if hasattr(est, 'n_features_') and est.n_features_ != X.shape[1]:
        raise ValueError('X.shape[1] does not match est.n_features_')
    n_features = X.shape[1]

    if line_kw is None:
        line_kw = {'color': 'green'}
    if contour_kw is None:
        contour_kw = {}

    # convert feature_names to list
    if feature_names is None:
        # if not feature_names use fx indices as name
        feature_names = [str(i) for i in range(n_features)]
    elif isinstance(feature_names, np.ndarray):
        feature_names = feature_names.tolist()

    def convert_feature(fx):
        if isinstance(fx, six.string_types):
            try:
                fx = feature_names.index(fx)
            except ValueError:
                raise ValueError('Feature %s not in feature_names' % fx)
        return fx

    # convert features into a seq of int tuples
    tmp_features = []
    for fxs in features:
        if isinstance(fxs, (numbers.Integral,) + six.string_types):
            fxs = (fxs,)
        try:
            fxs = np.array([convert_feature(fx) for fx in fxs], dtype=np.int32)
        except TypeError:
            raise ValueError('features must be either int, str, or tuple '
                             'of int/str')
        if not (1 <= np.size(fxs) <= 2):
            raise ValueError('target features must be either one or two')

        tmp_features.append(fxs)

    features = tmp_features

    names = []
    try:
        for fxs in features:
            l = []
            # explicit loop so "i" is bound for exception below
            for i in fxs:
                l.append(feature_names[i])
            names.append(l)
    except IndexError:
        raise ValueError('All entries of features must be less than '
                         'len(feature_names) = {0}, got {1}.'
                         .format(len(feature_names), i))

    # compute PD functions
    pd_result = Parallel(n_jobs=n_jobs, verbose=verbose)(
        delayed(partial_dependence)(est, fxs, X=X, method=method,
                                    grid_resolution=grid_resolution,
                                    percentiles=percentiles)
        for fxs in features)

    # Need to check if output param is valid. We can only do that now that we
    # have the predictions:
    if is_regressor and "MultiTask" in est.__class__.__name__:
        pdp, _ = pd_result[0]
        if not 0 <= output <= pdp.shape[0]:
                raise ValueError(
                    'output must be in [0, n_tasks], got {}.'.format(
                        target_idx))

    # get global min and max values of PD grouped by plot type
    pdp_lim = {}
    for pdp, axes in pd_result:
        min_pd, max_pd = pdp[target_idx].min(), pdp[target_idx].max()
        n_fx = len(axes)
        old_min_pd, old_max_pd = pdp_lim.get(n_fx, (min_pd, max_pd))
        min_pd = min(min_pd, old_min_pd)
        max_pd = max(max_pd, old_max_pd)
        pdp_lim[n_fx] = (min_pd, max_pd)

    # create contour levels for two-way plots
    if 2 in pdp_lim:
        Z_level = np.linspace(*pdp_lim[2], num=8)

    if ax is None:
        fig = plt.figure(**fig_kw)
    else:
        fig = ax.get_figure()
        fig.clear()

    n_cols = min(n_cols, len(features))
    n_rows = int(np.ceil(len(features) / float(n_cols)))
    axs = []
    for i, fx, name, (pdp, axes) in zip(count(), features, names,
                                        pd_result):
        ax = fig.add_subplot(n_rows, n_cols, i + 1)

        if len(axes) == 1:
            ax.plot(axes[0], pdp[target_idx].ravel(), **line_kw)
        else:
            # make contour plot
            assert len(axes) == 2
            XX, YY = np.meshgrid(axes[0], axes[1])
            Z = pdp[target_idx].reshape(list(map(np.size, axes))).T
            CS = ax.contour(XX, YY, Z, levels=Z_level, linewidths=0.5,
                            colors='k')
            ax.contourf(XX, YY, Z, levels=Z_level, vmax=Z_level[-1],
                        vmin=Z_level[0], alpha=0.75, **contour_kw)
            ax.clabel(CS, fmt='%2.2f', colors='k', fontsize=10, inline=True)

        # plot data deciles + axes labels
        deciles = mquantiles(X[:, fx[0]], prob=np.arange(0.1, 1.0, 0.1))
        trans = transforms.blended_transform_factory(ax.transData,
                                                     ax.transAxes)
        ylim = ax.get_ylim()
        ax.vlines(deciles, [0], 0.05, transform=trans, color='k')
        ax.set_xlabel(name[0])
        ax.set_ylim(ylim)

        # prevent x-axis ticks from overlapping
        ax.xaxis.set_major_locator(MaxNLocator(nbins=6, prune='lower'))
        tick_formatter = ScalarFormatter()
        tick_formatter.set_powerlimits((-3, 4))
        ax.xaxis.set_major_formatter(tick_formatter)

        if len(axes) > 1:
            # two-way PDP - y-axis deciles + labels
            deciles = mquantiles(X[:, fx[1]], prob=np.arange(0.1, 1.0, 0.1))
            trans = transforms.blended_transform_factory(ax.transAxes,
                                                         ax.transData)
            xlim = ax.get_xlim()
            ax.hlines(deciles, [0], 0.05, transform=trans, color='k')
            ax.set_ylabel(name[1])
            # hline erases xlim
            ax.set_xlim(xlim)
        else:
            ax.set_ylabel('Partial dependence')

        if len(axes) == 1:
            ax.set_ylim(pdp_lim[1])
        axs.append(ax)

    fig.subplots_adjust(bottom=0.15, top=0.7, left=0.1, right=0.95, wspace=0.4,
                        hspace=0.3)
    return fig, axs
