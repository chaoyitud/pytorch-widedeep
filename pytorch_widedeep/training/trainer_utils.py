"""
Code for 'Alias' and 'set_default_attr' taken from the one and only Hunter
McGushion and his library:
https://github.com/HunterMcGushion/hyperparameter_hunter
"""

import numpy as np
import wrapt
from tqdm import tqdm
from torch import nn
from sklearn.model_selection import train_test_split

from pytorch_widedeep.losses import MSLELoss, RMSELoss, FocalLoss, RMSLELoss
from pytorch_widedeep.wdtypes import (
    Any,
    Dict,
    List,
    Union,
    Optional,
    Transforms,
)
from pytorch_widedeep.training._wd_dataset import WideDeepDataset
from pytorch_widedeep.training._loss_and_obj_aliases import (
    _LossAliases,
    _ObjectiveToMethod,
)


def wd_train_val_split(  # noqa: C901
    seed: int,
    method: str,
    X_wide: Optional[np.ndarray] = None,
    X_tab: Optional[np.ndarray] = None,
    X_text: Optional[np.ndarray] = None,
    X_img: Optional[np.ndarray] = None,
    X_train: Optional[Dict[str, np.ndarray]] = None,
    X_val: Optional[Dict[str, np.ndarray]] = None,
    val_split: Optional[float] = None,
    target: Optional[np.ndarray] = None,
    transforms: Optional[List[Transforms]] = None,
):
    r"""
    Function to create the train/val split for a wide and deep model

    If a validation set (X_val) is passed to the fit method, or val_split is
    specified, the train/val split will happen internally. A number of options
    are allowed in terms of data inputs. For parameter information, please,
    see the ``Trainer``'s' ``.fit()`` method documentation

    Parameters
    ----------
    seed: int
        random seed to be used during train/val split
    method: str
        'regression',  'binary' or 'multiclass'
    X_wide: np.ndarray, Optional, default = None
        wide dataset
    X_tab: np.ndarray, Optional, default = None
        tabular dataset (categorical and continuous features)
    X_img: np.ndarray, Optional, default = None
        image dataset
    X_text: np.ndarray, Optional, default = None
        text dataset
    X_val: Dict, Optional, default = None
        Dict with the validation set, where the keys are the component names
        (e.g: 'wide') and the values the corresponding arrays
    val_split: float, Optional, default = None
        Alternatively, the validation split can be specified via a float
    target: np.ndarray, Optional, default = None
    transforms: List, Optional, default = None
        List of Transforms to be applied to the image dataset

    Returns
    -------
    train_set: WideDeepDataset
        train ``WideDeepDataset`` object
    eval_set: WideDeepDataset
        validation ``WideDeepDataset`` object
    """

    if X_val is not None:
        assert (
            X_train is not None
        ), "if the validation set is passed as a dictionary, the training set must also be a dictionary"
        train_set = WideDeepDataset(**X_train, transforms=transforms)  # type: ignore
        eval_set = WideDeepDataset(**X_val, transforms=transforms)  # type: ignore
    elif val_split is not None:
        if not X_train:
            X_train = _build_train_dict(X_wide, X_tab, X_text, X_img, target)
        y_tr, y_val, idx_tr, idx_val = train_test_split(
            X_train["target"],
            np.arange(len(X_train["target"])),
            test_size=val_split,
            random_state=seed,
            stratify=X_train["target"] if method != "regression" else None,
        )
        X_tr, X_val = {"target": y_tr}, {"target": y_val}
        if "X_wide" in X_train.keys():
            X_tr["X_wide"], X_val["X_wide"] = (
                X_train["X_wide"][idx_tr],
                X_train["X_wide"][idx_val],
            )
        if "X_tab" in X_train.keys():
            X_tr["X_tab"], X_val["X_tab"] = (
                X_train["X_tab"][idx_tr],
                X_train["X_tab"][idx_val],
            )
        if "X_text" in X_train.keys():
            X_tr["X_text"], X_val["X_text"] = (
                X_train["X_text"][idx_tr],
                X_train["X_text"][idx_val],
            )
        if "X_img" in X_train.keys():
            X_tr["X_img"], X_val["X_img"] = (
                X_train["X_img"][idx_tr],
                X_train["X_img"][idx_val],
            )
        train_set = WideDeepDataset(**X_tr, transforms=transforms)  # type: ignore
        eval_set = WideDeepDataset(**X_val, transforms=transforms)  # type: ignore
    else:
        if not X_train:
            X_train = _build_train_dict(X_wide, X_tab, X_text, X_img, target)
        train_set = WideDeepDataset(**X_train, transforms=transforms)  # type: ignore
        eval_set = None

    return train_set, eval_set


def _build_train_dict(X_wide, X_tab, X_text, X_img, target):
    X_train = {"target": target}
    if X_wide is not None:
        X_train["X_wide"] = X_wide
    if X_tab is not None:
        X_train["X_tab"] = X_tab
    if X_text is not None:
        X_train["X_text"] = X_text
    if X_img is not None:
        X_train["X_img"] = X_img
    return X_train


def print_loss_and_metric(pb: tqdm, loss: float, score: Dict):
    r"""
    Function to improve readability and avoid code repetition in the
    training/validation loop within the Trainer's fit method

    Parameters
    ----------
    pb: tqdm
        tqdm Object defined as trange(...)
    loss: float
        loss value
    score: Dict
        Dictionary where the keys are the metric names and the values are the
        corresponding values
    """
    if score is not None:
        pb.set_postfix(
            metrics={k: np.round(v, 4) for k, v in score.items()},
            loss=loss,
        )
    else:
        pb.set_postfix(loss=loss)


def save_epoch_logs(epoch_logs: Dict, loss: float, score: Dict, stage: str):
    """
    Function to improve readability and avoid code repetition in the
    training/validation loop within the Trainer's fit method

    Parameters
    ----------
    epoch_logs: Dict
        Dict containing the epoch logs
    loss: float
        loss value
    score: Dict
        Dictionary where the keys are the metric names and the values are the
        corresponding values
    stage: str
        one of 'train' or 'val'
    """
    epoch_logs["_".join([stage, "loss"])] = loss
    if score is not None:
        for k, v in score.items():
            log_k = "_".join([stage, k])
            epoch_logs[log_k] = v
    return epoch_logs


def alias_to_loss(loss_fn: str, **kwargs):
    r"""
    Function that returns the corresponding loss function given an alias

    Parameters
    ----------
    loss_fn: str
        Loss name or alias

    Returns
    -------
    Object
        loss function

    Examples
    --------
    >>> from pytorch_widedeep.training.trainer_utils import alias_to_loss
    >>> loss_fn = alias_to_loss(loss_fn="binary_logloss", weight=None)
    """
    if loss_fn not in _ObjectiveToMethod.keys():
        raise ValueError(
            "objective or loss function is not supported. Please consider passing a callable "
            "directly to the compile method (see docs) or use one of the supported objectives "
            "or loss functions: {}".format(", ".join(_ObjectiveToMethod.keys()))
        )
    if loss_fn in _LossAliases.get("binary"):
        return nn.BCEWithLogitsLoss(weight=kwargs["weight"])
    if loss_fn in _LossAliases.get("multiclass"):
        return nn.CrossEntropyLoss(weight=kwargs["weight"])
    if loss_fn in _LossAliases.get("regression"):
        return nn.MSELoss()
    if loss_fn in _LossAliases.get("mean_absolute_error"):
        return nn.L1Loss()
    if loss_fn in _LossAliases.get("mean_squared_log_error"):
        return MSLELoss()
    if loss_fn in _LossAliases.get("root_mean_squared_error"):
        return RMSELoss()
    if loss_fn in _LossAliases.get("root_mean_squared_log_error"):
        return RMSLELoss()
    if "focal_loss" in loss_fn:
        return FocalLoss(**kwargs)


class Alias:
    def __init__(self, primary_name: str, aliases: Union[str, List[str]]):
        r"""Convert uses of `aliases` to `primary_name` upon calling the decorated
        function/method

        Parameters
        ----------
        primary_name: String
            Preferred name for the parameter, the value of which will be set
            to the value of the used alias. If `primary_name` is already
            explicitly used on call in addition to any aliases, the value of
            `primary_name` will remain unchanged. It only assumes the value of
            an alias if the `primary_name` is not used
        aliases: List, string
            One or multiple string aliases for `primary_name`. If
            `primary_name` is not used on call, its value will be set to that
            of a random alias in `aliases`. Before calling the decorated
            callable, all `aliases` are removed from its kwargs

        Examples
        --------
        >>> class Foo():
        ...     @Alias("a", ["a2"])
        ...     def __init__(self, a, b=None):
        ...         print(a, b)
        >>> @Alias("a", ["a2"])
        ... @Alias("b", ["b2"])
        ... def bar(a, b=None):
        ...    print(a, b)
        >>> foo = Foo(a2="x", b="y")
        x y
        >>> bar(a2="x", b2="y")
        x y"""
        self.primary_name = primary_name
        self.aliases = aliases if isinstance(aliases, list) else [aliases]

    @wrapt.decorator
    def __call__(self, wrapped, instance, args, kwargs):
        for alias in set(self.aliases).intersection(kwargs):
            # Only set if no `primary_name` already. Remove `aliases`, leaving only `primary_name`
            kwargs.setdefault(self.primary_name, kwargs.pop(alias))
            # Record aliases used in `instance.__wd_aliases_used` or `wrapped.__wd_aliases_used`
            if instance:
                set_default_attr(instance, "__wd_aliases_used", {})[
                    self.primary_name
                ] = alias
            else:
                set_default_attr(wrapped, "__wd_aliases_used", {})[
                    self.primary_name
                ] = alias
        return wrapped(*args, **kwargs)


def set_default_attr(obj: Any, name: str, value: Any):
    r"""Set the `name` attribute of `obj` to `value` if the attribute does not
    already exist

    Parameters
    ----------
    obj: Object
        Object whose `name` attribute will be returned (after setting it to
        `value`, if necessary)
    name: String
        Name of the attribute to set to `value`, or to return
    value: Object
        Default value to give to `obj.name` if the attribute does not already
        exist

    Returns
    -------
    Object
        `obj.name` if it exists. Else, `value`

    Examples
    --------
    >>> foo = type("Foo", tuple(), {"my_attr": 32})
    >>> set_default_attr(foo, "my_attr", 99)
    32
    >>> set_default_attr(foo, "other_attr", 9000)
    9000
    >>> assert foo.my_attr == 32
    >>> assert foo.other_attr == 9000
    """
    try:
        return getattr(obj, name)
    except AttributeError:
        setattr(obj, name, value)
    return value
