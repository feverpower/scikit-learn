"""
General tests for all estimators in sklearn.
"""

# Authors: Andreas Mueller <amueller@ais.uni-bonn.de>
#          Gael Varoquaux gael.varoquaux@normalesup.org
# License: BSD 3 clause

import os
import warnings
import sys
import re
import pkgutil
from inspect import isgenerator
from functools import partial

import pytest
import numpy as np

from sklearn.utils import all_estimators
from sklearn.utils._testing import ignore_warnings
from sklearn.exceptions import ConvergenceWarning, SkipTestWarning
from sklearn.utils.estimator_checks import check_estimator

import sklearn
from sklearn.base import BiclusterMixin

from sklearn.decomposition import NMF
from sklearn.utils.validation import check_non_negative, check_array
from sklearn.linear_model._base import LinearClassifierMixin
from sklearn.linear_model import LogisticRegression
from sklearn.svm import NuSVC
from sklearn.utils import IS_PYPY
from sklearn.utils._testing import SkipTest
from sklearn.utils.estimator_checks import (
    _construct_instance,
    _set_checking_parameters,
    _get_check_estimator_ids,
    check_class_weight_balanced_linear_classifier,
    parametrize_with_checks,
    check_transformer_get_feature_names_out)


def test_all_estimator_no_base_class():
    # test that all_estimators doesn't find abstract classes.
    for name, Estimator in all_estimators():
        msg = ("Base estimators such as {0} should not be included"
               " in all_estimators").format(name)
        assert not name.lower().startswith('base'), msg


def _sample_func(x, y=1):
    pass


@pytest.mark.parametrize("val, expected", [
    (partial(_sample_func, y=1), "_sample_func(y=1)"),
    (_sample_func, "_sample_func"),
    (partial(_sample_func, 'world'), "_sample_func"),
    (LogisticRegression(C=2.0), "LogisticRegression(C=2.0)"),
    (LogisticRegression(random_state=1, solver='newton-cg',
                        class_weight='balanced', warm_start=True),
     "LogisticRegression(class_weight='balanced',random_state=1,"
     "solver='newton-cg',warm_start=True)")
])
def test_get_check_estimator_ids(val, expected):
    assert _get_check_estimator_ids(val) == expected


def _tested_estimators(type_filter=None):
    for name, Estimator in all_estimators(type_filter):
        if issubclass(Estimator, BiclusterMixin):
            continue
        try:
            estimator = _construct_instance(Estimator)
        except SkipTest:
            continue

        yield estimator


@parametrize_with_checks(list(_tested_estimators()))
def test_estimators(estimator, check, request):
    # Common tests for estimator instances
    with ignore_warnings(category=(FutureWarning,
                                   ConvergenceWarning,
                                   UserWarning, FutureWarning)):
        _set_checking_parameters(estimator)
        check(estimator)


def test_check_estimator_generate_only():
    all_instance_gen_checks = check_estimator(LogisticRegression(),
                                              generate_only=True)
    assert isgenerator(all_instance_gen_checks)


@ignore_warnings(category=(DeprecationWarning, FutureWarning))
# ignore deprecated open(.., 'U') in numpy distutils
def test_configure():
    # Smoke test the 'configure' step of setup, this tests all the
    # 'configure' functions in the setup.pys in scikit-learn
    # This test requires Cython which is not necessarily there when running
    # the tests of an installed version of scikit-learn or when scikit-learn
    # is installed in editable mode by pip build isolation enabled.
    pytest.importorskip("Cython")
    cwd = os.getcwd()
    setup_path = os.path.abspath(os.path.join(sklearn.__path__[0], '..'))
    setup_filename = os.path.join(setup_path, 'setup.py')
    if not os.path.exists(setup_filename):
        pytest.skip('setup.py not available')
    # XXX unreached code as of v0.22
    try:
        os.chdir(setup_path)
        old_argv = sys.argv
        sys.argv = ['setup.py', 'config']

        with warnings.catch_warnings():
            # The configuration spits out warnings when not finding
            # Blas/Atlas development headers
            warnings.simplefilter('ignore', UserWarning)
            with open('setup.py') as f:
                exec(f.read(), dict(__name__='__main__'))
    finally:
        sys.argv = old_argv
        os.chdir(cwd)


def _tested_linear_classifiers():
    classifiers = all_estimators(type_filter='classifier')

    with warnings.catch_warnings(record=True):
        for name, clazz in classifiers:
            required_parameters = getattr(clazz, "_required_parameters", [])
            if len(required_parameters):
                # FIXME
                continue

            if ('class_weight' in clazz().get_params().keys() and
                    issubclass(clazz, LinearClassifierMixin)):
                yield name, clazz


@pytest.mark.parametrize("name, Classifier",
                         _tested_linear_classifiers())
def test_class_weight_balanced_linear_classifiers(name, Classifier):
    check_class_weight_balanced_linear_classifier(name, Classifier)


@ignore_warnings
def test_import_all_consistency():
    # Smoke test to check that any name in a __all__ list is actually defined
    # in the namespace of the module or package.
    pkgs = pkgutil.walk_packages(path=sklearn.__path__, prefix='sklearn.',
                                 onerror=lambda _: None)
    submods = [modname for _, modname, _ in pkgs]
    for modname in submods + ['sklearn']:
        if ".tests." in modname:
            continue
        if IS_PYPY and ('_svmlight_format_io' in modname or
                        'feature_extraction._hashing_fast' in modname):
            continue
        package = __import__(modname, fromlist="dummy")
        for name in getattr(package, '__all__', ()):
            assert hasattr(package, name),\
                "Module '{0}' has no attribute '{1}'".format(modname, name)


def test_root_import_all_completeness():
    EXCEPTIONS = ('utils', 'tests', 'base', 'setup', 'conftest')
    for _, modname, _ in pkgutil.walk_packages(path=sklearn.__path__,
                                               onerror=lambda _: None):
        if '.' in modname or modname.startswith('_') or modname in EXCEPTIONS:
            continue
        assert modname in sklearn.__all__


def test_all_tests_are_importable():
    # Ensure that for each contentful subpackage, there is a test directory
    # within it that is also a subpackage (i.e. a directory with __init__.py)

    HAS_TESTS_EXCEPTIONS = re.compile(r'''(?x)
                                      \.externals(\.|$)|
                                      \.tests(\.|$)|
                                      \._
                                      ''')
    lookup = {name: ispkg
              for _, name, ispkg
              in pkgutil.walk_packages(sklearn.__path__, prefix='sklearn.')}
    missing_tests = [name for name, ispkg in lookup.items()
                     if ispkg
                     and not HAS_TESTS_EXCEPTIONS.search(name)
                     and name + '.tests' not in lookup]
    assert missing_tests == [], ('{0} do not have `tests` subpackages. '
                                 'Perhaps they require '
                                 '__init__.py or an add_subpackage directive '
                                 'in the parent '
                                 'setup.py'.format(missing_tests))


def test_class_support_removed():
    # Make sure passing classes to check_estimator or parametrize_with_checks
    # raises an error

    msg = "Passing a class was deprecated.* isn't supported anymore"
    with pytest.raises(TypeError, match=msg):
        check_estimator(LogisticRegression)

    with pytest.raises(TypeError, match=msg):
        parametrize_with_checks([LogisticRegression])


class MyNMFWithBadErrorMessage(NMF):
    # Same as NMF but raises an uninformative error message if X has negative
    # value. This estimator would fail the check suite in strict mode,
    # specifically it would fail check_fit_non_negative
    def fit(self, X, y=None, **params):
        X = check_array(X, accept_sparse=('csr', 'csc'),
                        dtype=[np.float64, np.float32])
        try:
            check_non_negative(X, whom='')
        except ValueError:
            raise ValueError("Some non-informative error msg")

        return super().fit(X, y, **params)


def test_strict_mode_check_estimator():
    # Tests various conditions for the strict mode of check_estimator()
    # Details are in the comments

    # LogisticRegression has no _xfail_checks, so when strict_mode is on, there
    # should be no skipped tests.
    with pytest.warns(None) as catched_warnings:
        check_estimator(LogisticRegression(), strict_mode=True)
    assert not any(isinstance(w, SkipTestWarning) for w in catched_warnings)
    # When strict mode is off, check_n_features should be skipped because it's
    # a fully strict check
    msg_check_n_features_in = 'check_n_features_in is fully strict '
    with pytest.warns(SkipTestWarning, match=msg_check_n_features_in):
        check_estimator(LogisticRegression(), strict_mode=False)

    # NuSVC has some _xfail_checks. They should be skipped regardless of
    # strict_mode
    with pytest.warns(SkipTestWarning,
                      match='fails for the decision_function method'):
        check_estimator(NuSVC(), strict_mode=True)
    # When strict mode is off, check_n_features_in is skipped along with the
    # rest of the xfail_checks
    with pytest.warns(SkipTestWarning, match=msg_check_n_features_in):
        check_estimator(NuSVC(), strict_mode=False)

    # MyNMF will fail check_fit_non_negative() in strict mode because it yields
    # a bad error message
    with pytest.raises(
        AssertionError, match="The error message should contain"
    ):
        check_estimator(MyNMFWithBadErrorMessage(), strict_mode=True)
    # However, it should pass the test suite in non-strict mode because when
    # strict mode is off, check_fit_non_negative() will not check the exact
    # error messsage. (We still assert that the warning from
    # check_n_features_in is raised)
    with pytest.warns(SkipTestWarning, match=msg_check_n_features_in):
        check_estimator(MyNMFWithBadErrorMessage(), strict_mode=False)


@parametrize_with_checks([LogisticRegression(),
                          NuSVC(),
                          MyNMFWithBadErrorMessage()],
                         strict_mode=False)
def test_strict_mode_parametrize_with_checks(estimator, check):
    # Ideally we should assert that the strict checks are Xfailed...
    check(estimator)


# TODO: As more modules support get_feature_names_out they should be removed
# from this list to be tested
GET_FEATURES_OUT_MODULES_TO_IGNORE = [
    'cluster',
    'cross_decomposition',
    'decomposition',
    'discriminant_analysis',
    'ensemble',
    'impute',
    'isotonic',
    'kernel_approximation',
    'manifold',
    'neighbors',
    'neural_network',
    'random_projection'
]

GET_FEATURES_OUT_ESTIMATORS = [
   est for est in _tested_estimators('transformer')
   if "2darray" in est._get_tags()["X_types"] and
   not est._get_tags()["no_validation"] and
   est.__module__.split('.')[1] not in GET_FEATURES_OUT_MODULES_TO_IGNORE
]


@pytest.mark.parametrize("transformer", GET_FEATURES_OUT_ESTIMATORS)
def test_transformers_get_feature_names_out(transformer):
    check_transformer_get_feature_names_out(type(transformer).__name__,
                                            transformer)
