import inspect
import numbers
import typing

from typing import TYPE_CHECKING
from typing import Union
from typing import Any

import numpy as np

RandomState = Union[int, np.random.RandomState, None]

if TYPE_CHECKING:
    from typing_extensions import Literal  # type: ignore  # noqa
else:
    Literal = None


def _get_annotation_class_name(annotation):
    """Get class name for annnotation"""
    if annotation is None:
        return 'None'
    elif annotation is Any:
        return 'Any'

    if getattr(annotation, '__qualname__', None):
        return annotation.__qualname__
    elif getattr(annotation, '_name', None):
        # generic for >= 3.7
        return annotation._name

    origin = getattr(annotation, '__origin__', None)
    if origin:
        return _get_annotation_class_name(annotation.__origin__)

    # generic for < 3.7 (Literal)
    return annotation.__class__.__qualname__.lstrip('_')


def _format_docstring_annotation(annotation):
    """Convert annotation to docstring."""
    class_name = _get_annotation_class_name(annotation)

    if class_name == 'BaseEstimator':
        return 'estimator instance'
    elif class_name == 'NoneType':
        return 'None'
    elif class_name == 'RandomState':
        return 'RandomState instance'
    elif class_name == 'Union':
        values = [_format_docstring_annotation(t) for t in annotation.__args__]
        if len(values) == 2:
            return ' or '.join(values)
        first = ', '.join(values[:-1])
        return f'{first} or {values[-1]}'
    elif class_name == 'Literal':
        if hasattr(annotation, '__values__'):
            # For Python == 3.6 support
            args = annotation.__values__
        else:
            args = annotation.__args__
        items = [repr(t) for t in args]
        if len(items) == 1:
            return items[0]
        values = ', '.join(items)
        return f'{{{values}}}'
    elif class_name == 'List':
        values = ', '.join(_format_docstring_annotation(t)
                           for t in annotation.__args__)
        return f'list of {values}'

    return class_name


def get_docstring_annotations(obj):
    """Get human readable docstring for types for a obj with annotations.

    This function requires `typing_extensions` to be installed to run.

    Parameters
    ----------
    obj: object
        Object to get annotations from

    Returns
    -------
    output: dict
        dictionary mapping from name to human-readable docstring.
    """
    if not hasattr(obj, '__annotations__'):
        return {}

    from typing_extensions import Literal
    annotations = typing.get_type_hints(obj, {'Literal': Literal})
    # get defaults
    params = inspect.signature(obj).parameters
    defaults = {p: v.default for p, v in params.items()
                if v.default != inspect.Parameter.empty}

    output = {}
    for name, annotation in annotations.items():
        anno = _format_docstring_annotation(annotation)
        if name in defaults:
            default = defaults[name]
            if (isinstance(default, numbers.Real) and
                    not isinstance(default, numbers.Integral)):
                # For floats the representation can vary, i.e:
                # default=np.inf or default=1e-4
                anno += ", default="
            else:
                anno += f", default={repr(default)}"
        output[name] = anno
    return output
