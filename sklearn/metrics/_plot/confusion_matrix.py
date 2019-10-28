from itertools import product

import numpy as np

from .. import confusion_matrix
from ...utils import check_matplotlib_support
from ...utils.multiclass import unique_labels
from ...base import is_classifier


class ConfusionMatrixDisplay:
    """Confusion Matrix visualization.

    It is recommend to use :func:`~sklearn.metrics.plot_confusion_matrix` to
    create a :class:`ConfusionMatrixDisplay`. All parameters are stored as
    attributes.

    Read more in the :ref:`User Guide <confusion_matrix>`.

    Parameters
    ----------
    confusion_matrix : ndarray of shape (n_classes, n_classes)
        Confusion matrix.

    display_labels : ndarray of shape (n_classes,)
        Display labels for plot.

    Attributes
    ----------
    im_: matplotlib AxesImage
        Image representing the confusion matrix.

    text_: ndarray of shape (n_classes, n_classes), dtype=matplotlib Text, or \
           `None`
        Array of matplotlib axes. `None` if `include_values` is false.

    ax_ : matplotlib Axes
        Axes with confusion matrix.

    figure_ : matplotlib Figure
        Figure containing the confusion matrix.
    """
    def __init__(self, confusion_matrix, display_labels):
        self.confusion_matrix = confusion_matrix
        self.display_labels = display_labels

    def plot(self, include_values=True, cmap='viridis',
             xticks_rotation='horizontal', values_format=None, ax=None):
        """Plot visualization.

        Parameters
        ----------
        include_values : bool, default=True
            Includes values in confusion matrix.

        cmap : str or matplotlib Colormap, default='viridis'
            Colormap recognized by matplotlib.

        xticks_rotation : {'vertical', 'horizontal'} or float, \
                         default='vertical'
            Rotation of xtick labels.

        values_format : str, default=None
            Format specification for values in confusion matrix. If None,
            the format specification is '.2f' for a normalized matrix, and
            'd' for a unnormalized matrix.

        ax : matplotlib axes, default=None
            Axes object to plot on. If `None`, a new figure and axes is
            created.

        Returns
        -------
        display : :class:`~sklearn.metrics.ConfusionMatrixDisplay`
        """
        check_matplotlib_support("ConfusionMatrixDisplay.plot")
        import matplotlib.pyplot as plt

        if ax is None:
            fig, ax = plt.subplots()
        else:
            fig = ax.figure

        cm = self.confusion_matrix
        normalized = np.issubdtype(cm.dtype, np.float_)
        self.im_ = ax.imshow(cm, interpolation='nearest', cmap=cmap)
        self.text_ = None

        cmap_min, cmap_max = self.im_.cmap(0), self.im_.cmap(256)

        if include_values:
            self.text_ = np.empty_like(cm, dtype=object)
            if values_format is None:
                values_format = '.2f' if normalized else 'd'
            thresh = (cm.max() - cm.min()) / 2.
            for i, j in product(range(cm.shape[0]), range(cm.shape[1])):
                color = cmap_max if cm[i, j] < thresh else cmap_min
                self.text_[i, j] = ax.text(j, i,
                                           format(cm[i, j], values_format),
                                           ha="center", va="center",
                                           color=color)

        fig.colorbar(self.im_, ax=ax)
        ax.set(xticks=np.arange(cm.shape[1]),
               yticks=np.arange(cm.shape[0]),
               xticklabels=self.display_labels,
               yticklabels=self.display_labels,
               ylabel="True label",
               xlabel="Predicted label")

        plt.setp(ax.get_xticklabels(), rotation=xticks_rotation)

        self.figure_ = fig
        self.ax_ = ax
        return self


def plot_confusion_matrix(estimator, X, y_true, sample_weight=None,
                          labels=None, display_labels=None,
                          include_values=True, normalize=False,
                          xticks_rotation='horizontal',
                          values_format=None,
                          cmap='viridis', ax=None):
    """Plot Confusion Matrix.

    Read more in the :ref:`User Guide <visualizations>`.

    Parameters
    ----------
    estimator : estimator instance
        Trained classifier.

    X : {array-like, sparse matrix} of shape (n_samples, n_features)
        Input values.

    y : array-like of shape (n_samples,)
        Target values.

    sample_weight : array-like of shape (n_samples,), default=None
        Sample weights.

    labels : array-like of shape (n_classes,), default=None
        List of labels to index the matrix. This may be used to reorder or
        select a subset of labels. If `None` is given, those that appear at
        least once in `y_true` or `y_pred` are used in sorted order.

    display_labels : array-like of shape (n_classes,), default=None
        Target names used for plotting. By default, `labels` will be used if
        it is defined, otherwise the unique labels of `y_true` and `y_pred`
        will be used.

    include_values : bool, default=True
        Includes values in confusion matrix.

    normalize : bool, default=False
        Normalizes confusion matrix.

    xticks_rotation : {'vertical', 'horizontal'} or float, \
                        default='vertical'
        Rotation of xtick labels.

    values_format : str, default=None
        Format specification for values in confusion matrix. If None,
        the format specification is '.2f' for a normalized matrix, and
        'd' for a unnormalized matrix.

    cmap : str or matplotlib Colormap, default='viridis'
        Colormap recognized by matplotlib.

    ax : matplotlib Axes, default=None
        Axes object to plot on. If `None`, a new figure and axes is
        created.

    Returns
    -------
    display: :class:`~sklearn.metrics.ConfusionMatrixDisplay`
    """
    check_matplotlib_support("plot_confusion_matrix")

    if not is_classifier(estimator):
        raise ValueError("plot_confusion_matrix only supports classifiers")

    y_pred = estimator.predict(X)
    cm = confusion_matrix(y_true, y_pred, sample_weight=sample_weight,
                          labels=labels)
    if normalize:
        cm = cm.astype('float') / cm.sum(axis=1)[:, None]

    if display_labels is None:
        if labels is None:
            display_labels = unique_labels(y_true, y_pred)
        else:
            display_labels = labels

    disp = ConfusionMatrixDisplay(confusion_matrix=cm,
                                  display_labels=display_labels)
    return disp.plot(include_values=include_values,
                     cmap=cmap, ax=ax, xticks_rotation=xticks_rotation)
