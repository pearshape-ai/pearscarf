__version__ = "1.39.0"
__url__ = "https://github.com/pearshape-ai/pearscarf"

__all__ = ["__version__", "__url__"]

# Make installed expert packages importable from the experts/ folder.
# Temporary — replaced by the registry-driven discovery in a follow-up.
import sys as _sys
from pathlib import Path as _Path

_EXPERTS_DIR = _Path(__file__).parent.parent / "experts"
if _EXPERTS_DIR.is_dir():
    _path_str = str(_EXPERTS_DIR)
    if _path_str not in _sys.path:
        _sys.path.insert(0, _path_str)
