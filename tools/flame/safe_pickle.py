"""Load FLAME's .pkl files safely.

Python pickles can run arbitrary code when loaded. FLAME's files only need a
few numpy/scipy array types, so this loader allows exactly those and refuses
anything else.
"""

import pickle
import warnings

ALLOWED = {
    ("numpy", "dtype"),
    ("numpy", "ndarray"),
    ("numpy.core.numeric", "_frombuffer"),
    ("numpy._core.numeric", "_frombuffer"),
    ("numpy.core.multiarray", "_reconstruct"),
    ("numpy._core.multiarray", "_reconstruct"),
    ("scipy.sparse._csc", "csc_matrix"),
    ("scipy.sparse.csc", "csc_matrix"),
}


class _AllowListUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) not in ALLOWED:
            raise pickle.UnpicklingError(f"refusing to load {module}.{name}")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)  # numpy.core -> numpy._core
            return super().find_class(module, name)


def load(path):
    with open(path, "rb") as fh:
        return _AllowListUnpickler(fh, encoding="latin1").load()
