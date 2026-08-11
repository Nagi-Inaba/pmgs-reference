"""PMGS Reference public Python API."""

from importlib.metadata import PackageNotFoundError, version

from pmgs_reference.errors import PMGSQueryError
from pmgs_reference.store import PMGSStore

__all__ = ["PMGSQueryError", "PMGSStore", "__version__"]

try:
    __version__ = version("pmgs-reference")
except PackageNotFoundError:  # source-only execution before package installation
    __version__ = "0+unknown"
