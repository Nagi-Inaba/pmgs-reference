"""PMGS Reference public Python API."""

from pmgs_reference.errors import PMGSQueryError
from pmgs_reference.store import PMGSStore

__all__ = ["PMGSQueryError", "PMGSStore", "__version__"]

__version__ = "0.2.0"
