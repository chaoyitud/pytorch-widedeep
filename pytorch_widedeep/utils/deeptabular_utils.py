import warnings

import numpy as np
import torch
import pandas as pd
from scipy.ndimage import gaussian_filter1d
from sklearn.exceptions import NotFittedError
from scipy.signal.windows import triang

from pytorch_widedeep.wdtypes import (
    Dict,
    List,
    Union,
    Tensor,
    Literal,
    Optional,
)
from pytorch_widedeep.utils.general_utils import Alias

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None

__all__ = ["LabelEncoder", "find_bin", "get_kernel_window"]


class LabelEncoder:
    r"""Label Encode categorical values for multiple columns at once

    :information_source: **NOTE**:
    LabelEncoder reserves 0 for `unseen` new categories. This is convenient
    when defining the embedding layers, since we can just set padding idx to 0.

    Parameters
    ----------
    columns_to_encode: list, Optional, default = None
        List of strings containing the names of the columns to encode. If
        `None` all columns of type `object` in the dataframe will be label
        encoded.
    with_attention: bool, default = False
        Boolean indicating whether the preprocessed data will be passed to an
        attention-based model. Aliased as `for_transformer`.
    shared_embed: bool, default = False
        Boolean indicating if the embeddings will be "_shared_" when using
        attention-based models. The idea behind `shared_embed` is described
        in the Appendix A in the [TabTransformer paper](https://arxiv.org/abs/2012.06678):
        '_The goal of having column embedding is to enable the model to
        distinguish the classes in one column from those in the
        other columns_'. In other words, the idea is to let the model learn
        which column is embedded at the time. See: `pytorch_widedeep.models.transformers._layers.SharedEmbeddings`.

    Attributes
    ----------
    encoding_dict : Dict
        Dictionary containing the encoding mappings in the format, e.g. : <br/>
        `{'colname1': {'cat1': 1, 'cat2': 2, ...}, 'colname2': {'cat1': 1, 'cat2': 2, ...}, ...}`
    inverse_encoding_dict : Dict
        Dictionary containing the inverse encoding mappings in the format, e.g. : <br/>
        `{'colname1': {1: 'cat1', 2: 'cat2', ...}, 'colname2': {1: 'cat1', 2: 'cat2', ...}, ...}`

    """

    @Alias("with_attention", "for_transformer")
    def __init__(
        self,
        columns_to_encode: Optional[List[str]] = None,
        with_attention: bool = False,
        shared_embed: bool = False,
    ):
        self.columns_to_encode = columns_to_encode

        self.shared_embed = shared_embed
        self.with_attention = with_attention

        self.reset_embed_idx = not self.with_attention or self.shared_embed

    def partial_fit(self, chunk: pd.DataFrame) -> "LabelEncoder":  # noqa: C901
        """Main method. Creates encoding attributes.

        Returns
        -------
        LabelEncoder
            `LabelEncoder` fitted object
        """
        # this is meant to be run when the data is large and we pass a chunk
        # at a time. Therefore, we do not copy the input chunk as mutating a
        # chunk is ok
        if self.columns_to_encode is None:
            self.columns_to_encode = list(
                chunk.select_dtypes(include=["object"]).columns
            )
        else:
            # sanity check to make sure all categorical columns are in an adequate
            # format
            for col in self.columns_to_encode:
                chunk[col] = chunk[col].astype("O")

        unique_column_vals: Dict[str, List[str]] = {}
        for c in self.columns_to_encode:
            unique_column_vals[c] = chunk[c].unique().tolist()

        if not hasattr(self, "encoding_dict"):
            # we run the method 'partial_fit' for the 1st time
            self.encoding_dict: Dict[str, Dict[str, int]] = {}
            if "cls_token" in unique_column_vals and self.shared_embed:
                self.encoding_dict["cls_token"] = {"[CLS]": 0}
                del unique_column_vals["cls_token"]

            # leave 0 for padding/"unseen" categories. Also we need an
            # attribute to keep track of the encoding in case we use
            # attention and we do not re-start the index/counter
            self.cum_idx: int = 1
            for k, v in unique_column_vals.items():
                self.encoding_dict[k] = {
                    o: i + self.cum_idx for i, o in enumerate(unique_column_vals[k])
                }
                self.cum_idx = (
                    1
                    if self.reset_embed_idx
                    else self.cum_idx + len(unique_column_vals[k])
                )
        else:
            # the 'partial_fit' method has already run.
            # "cls_token" will have been added already
            if "cls_token" in unique_column_vals and self.shared_embed:
                del unique_column_vals["cls_token"]

            # Classes in the new chunk of the dataset that have not been seen
            # before
            unseen_classes: Dict[str, List[str]] = {}
            for c in self.columns_to_encode:
                unseen_classes[c] = list(
                    np.setdiff1d(
                        unique_column_vals[c], list(self.encoding_dict[c].keys())
                    )
                )

            # leave 0 for padding/"unseen" categories
            for k, v in unique_column_vals.items():
                # if we use attention we need to start encoding from the
                # last 'overall' encoding index. Otherwise, we use the max
                # encoding index per categorical col
                _idx = (
                    max(self.encoding_dict[k].values()) + 1
                    if self.reset_embed_idx
                    else self.cum_idx
                )
                if len(unseen_classes[k]) != 0:
                    for i, o in enumerate(unseen_classes[k]):
                        if o not in self.encoding_dict[k]:
                            self.encoding_dict[k][o] = i + _idx
                    # if self.reset_embed_idx is True it will be 1 anyway
                    self.cum_idx = (
                        1
                        if self.reset_embed_idx
                        else self.cum_idx + len(unseen_classes[k])
                    )

        return self

    def fit(self, df: pd.DataFrame) -> "LabelEncoder":
        """Runs update under the hood

        Returns
        -------
        LabelEncoder
            `LabelEncoder` fitted object
        """
        # this is meant to be run when the data fits in memory and therefore,
        # we do not want to mutate the original df, so we copy it
        self.partial_fit(df.copy())

        self.inverse_encoding_dict = self.create_inverse_encoding_dict()

        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Label Encoded the categories in `columns_to_encode`

        Returns
        -------
        pd.DataFrame
            label-encoded dataframe
        """
        try:
            self.encoding_dict
        except AttributeError:
            raise NotFittedError(
                "This LabelEncoder instance is not fitted yet. "
                "Call 'fit' with appropriate arguments before using this LabelEncoder."
            )

        df_inp = df.copy()
        # sanity check to make sure all categorical columns are in an adequate
        # format
        for col in self.columns_to_encode:  # type: ignore
            df_inp[col] = df_inp[col].astype("O")

        for k, v in self.encoding_dict.items():
            df_inp[k] = df_inp[k].apply(lambda x: v[x] if x in v.keys() else 0)

        return df_inp

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Combines `fit` and `transform`

        Examples
        --------

        >>> import pandas as pd
        >>> from pytorch_widedeep.utils import LabelEncoder
        >>> df = pd.DataFrame({'col1': [1,2,3], 'col2': ['me', 'you', 'him']})
        >>> columns_to_encode = ['col2']
        >>> encoder = LabelEncoder(columns_to_encode)
        >>> encoder.fit_transform(df)
           col1  col2
        0     1     1
        1     2     2
        2     3     3
        >>> encoder.encoding_dict
        {'col2': {'me': 1, 'you': 2, 'him': 3}}

        Returns
        -------
        pd.DataFrame
            label-encoded dataframe
        """
        return self.fit(df).transform(df)

    def create_inverse_encoding_dict(self) -> Dict[str, Dict[int, str]]:
        inverse_encoding_dict = dict()
        for c in self.encoding_dict:
            inverse_encoding_dict[c] = {v: k for k, v in self.encoding_dict[c].items()}
            inverse_encoding_dict[c][0] = "unseen"
        return inverse_encoding_dict

    def inverse_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Returns the original categories

        Examples
        --------

        >>> import pandas as pd
        >>> from pytorch_widedeep.utils import LabelEncoder
        >>> df = pd.DataFrame({'col1': [1,2,3], 'col2': ['me', 'you', 'him']})
        >>> columns_to_encode = ['col2']
        >>> encoder = LabelEncoder(columns_to_encode)
        >>> df_enc = encoder.fit_transform(df)
        >>> encoder.inverse_transform(df_enc)
           col1 col2
        0     1   me
        1     2  you
        2     3  him

        Returns
        -------
        pd.DataFrame
            DataFrame with original categories
        """

        if not hasattr(self, "inverse_encoding_dict"):
            self.inverse_encoding_dict = self.create_inverse_encoding_dict()

        for k, v in self.inverse_encoding_dict.items():
            df[k] = df[k].apply(lambda x: v[x])

        return df

    def __repr__(self) -> str:
        list_of_params: List[str] = []
        if self.columns_to_encode is not None:
            list_of_params.append("columns_to_encode={columns_to_encode}")
        if self.with_attention:
            list_of_params.append("with_attention={with_attention}")
        if self.shared_embed:
            list_of_params.append("shared_embed={shared_embed}")
        all_params = ", ".join(list_of_params)
        return f"LabelEncoder({all_params.format(**self.__dict__)})"


def find_bin(
    bin_edges: Union[np.ndarray, Tensor],
    values: Union[np.ndarray, Tensor],
    ret_value: bool = True,
) -> Union[np.ndarray, Tensor]:
    """Returns indices that are the results of applying the 'searchsorted' algo
    to 'bin_edges' and 'values' or the left edge of the bins (i.e. bin_edges[indices])

    Parameters
    ----------
    bin_edges: Union[np.ndarray, Tensor]
        monotonically increasing array of bin edges
    values: Union[np.ndarray, Tensor]
        values for which we want corresponding bins
    ret_value: bool
        if True, return bin values else indices

    Returns
    -------
    left_bin_edges: Union[np.ndarray, Tensor]
        left bin edges
    """
    if type(bin_edges) == np.ndarray and type(values) == np.ndarray:
        indices: Union[np.ndarray, Tensor] = np.searchsorted(
            bin_edges, values, side="left"
        )
        indices = np.where(
            (indices == 0) | (indices == len(bin_edges)), indices, indices - 1
        )
        indices = np.where(indices != len(bin_edges), indices, indices - 2)
    elif type(bin_edges) == Tensor and type(values) == Tensor:
        bin_edges = bin_edges.to(values.device)
        indices = torch.searchsorted(bin_edges, values, right=False)
        indices = torch.where(
            (indices == 0) | (indices == len(bin_edges)), indices, indices - 1
        )
        indices = torch.where(indices != len(bin_edges), indices, indices - 2)
    else:
        raise TypeError(
            "Both input arrays must be of teh same type, either np.ndarray of Tensor"
        )
    return indices if not ret_value else bin_edges[indices]  # type: ignore[index]


def _laplace(x, sigma: Union[int, float] = 2):
    return np.exp(-abs(x) / sigma) / (2.0 * sigma)


def get_kernel_window(
    kernel: Literal["gaussian", "triang", "laplace"] = "gaussian",
    ks: int = 5,
    sigma: Union[int, float] = 2,
) -> List[float]:
    """Procedure to prepare the window of values from symetrical kernel function
    for smoothing of the distribution in Label and Feature Distribution
    Smoothing (LDS & FDS).

    Parameters
    ----------
    kernel: Literal['gaussian', 'triang', 'laplace'] = 'gaussian'
        choice of kernel for label distribution smoothing
    ks: int = 5
        kernel size, i.e. count of samples in symmetric window
    sigma: Union[int,float] = 2
        standard deviation of ['gaussian','laplace'] kernel

    Returns
    -------
    kernel_window: list
        list with values from the chosen kernel function
    """
    half_ks = (ks - 1) // 2
    if kernel == "gaussian":
        base_kernel = [0.0] * half_ks + [1.0] + [0.0] * half_ks
        kernel_window = gaussian_filter1d(base_kernel, sigma=sigma)
    elif kernel == "triang":
        kernel_window = triang(ks) / sum(triang(ks))
    elif kernel == "laplace":
        kernel_window = list(map(_laplace, np.arange(-half_ks, half_ks + 1)))
    else:
        raise ValueError("Kernel can be only ['gaussian', 'triang', 'laplace'].")

    return kernel_window
