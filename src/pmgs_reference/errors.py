"""Structured errors shared by local PMGS Reference interfaces."""

from __future__ import annotations


class PMGSQueryError(ValueError):
    """A safe, machine-readable query error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        """Return the public error shape without internal paths or stack details."""
        return {"code": self.code, "message": self.message}


class ReleaseNotFoundError(PMGSQueryError):
    """Raised when the requested PMGS release is not in the canonical store."""

    def __init__(self, release: str) -> None:
        super().__init__("RELEASE_NOT_FOUND", f"PMGS release not found: {release}")


class EditionNotFoundError(PMGSQueryError):
    """Raised when an IPC edition is not in the requested release."""

    def __init__(self, edition: str) -> None:
        super().__init__("EDITION_NOT_FOUND", f"IPC edition not found: {edition}")


class DocumentNotFoundError(PMGSQueryError):
    """Raised when a document identifier is not in the requested store."""

    def __init__(self, document_id: str) -> None:
        super().__init__("DOCUMENT_NOT_FOUND", f"PMGS document not found: {document_id}")
