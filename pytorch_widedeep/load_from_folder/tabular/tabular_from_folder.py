import os
from typing import Type, Tuple, Union, Optional

import numpy as np
import pandas as pd

from pytorch_widedeep.preprocessing import (
    TabPreprocessor,
    WidePreprocessor,
    ChunkTabPreprocessor,
    ChunkWidePreprocessor,
)

TabularPreprocessor = Union[
    TabPreprocessor, WidePreprocessor, ChunkTabPreprocessor, ChunkWidePreprocessor
]


class TabFromFolder:
    def __init__(
        self,
        fname: str,
        directory: Optional[str] = None,
        target_col: Optional[str] = None,
        preprocessor: Optional[TabularPreprocessor] = None,
        text_col: Optional[str] = None,
        img_col: Optional[str] = None,
        reference: Type["TabFromFolder"] = None,
        ignore_target: bool = False,
    ):
        self.fname = fname

        if reference is not None:
            (
                self.directory,
                self.target_col,
                self.preprocessor,
                self.text_col,
                self.img_col,
            ) = self._set_from_reference(reference)
        else:
            assert (
                directory is not None
                or (target_col is not None and not ignore_target)
                or preprocessor is not None
            ), "if no reference is provided, 'directory', 'target_col' and 'preprocessor' must be provided"

            self.directory = directory
            self.target_col = target_col
            self.preprocessor = preprocessor
            self.text_col = text_col
            self.img_col = img_col

        assert (
            self.preprocessor.is_fitted
        ), "The preprocessor must be fitted before using this class"

        self.ignore_target = ignore_target

    def get_item(
        self, idx: int
    ) -> Tuple[np.ndarray, str, str, Optional[Union[int, float]]]:
        path = os.path.join(self.directory, self.fname)

        try:
            if not hasattr(self, "colnames"):
                self.colnames = pd.read_csv(path, nrows=0).columns.tolist()

            # TO DO: we need to look into this as the treatment is different whether
            # the csv contains headers or not

            _sample = pd.read_csv(
                path, skiprows=lambda x: x != idx + 1, header=None
            ).values
            sample = pd.DataFrame(_sample, columns=self.colnames)
        except Exception:
            raise ValueError("Currently only csv format is supported.")

        text_fname_or_text: str = (
            sample[self.text_col].to_list()[0] if self.text_col is not None else None
        )
        img_fname: str = (
            sample[self.img_col].to_list()[0] if self.img_col is not None else None
        )

        processed_sample = self.preprocessor.transform_sample(sample)

        if not self.ignore_target:
            target = sample[self.target_col].to_list()[0]
        else:
            target = None

        return processed_sample, text_fname_or_text, img_fname, target

    @staticmethod
    def _set_from_reference(
        reference: Type["TabFromFolder"],
    ) -> Tuple[str, str, TabularPreprocessor, Optional[str], Optional[str]]:
        return (
            reference.directory,
            reference.target_col,
            reference.preprocessor,
            reference.text_col,
            reference.img_col,
        )


class WideFromFolder(TabFromFolder):
    def __init__(
        self,
        fname: str,
        directory: Optional[str] = None,
        target_col: Optional[str] = None,
        preprocessor: Optional[TabularPreprocessor] = None,
        text_col: Optional[str] = None,
        img_col: Optional[str] = None,
        reference: Type["WideFromFolder"] = None,
        ignore_target: bool = False,
    ):
        super(WideFromFolder, self).__init__(
            fname=fname,
            directory=directory,
            target_col=target_col,
            preprocessor=preprocessor,
            text_col=text_col,
            img_col=img_col,
            reference=reference,
            ignore_target=ignore_target,
        )
