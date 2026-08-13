from __future__ import annotations

import shutil
from pathlib import Path

import pymupdf
import pytest

from pmgs_reference.ingest.build import build_database


def _copy_synthetic_pmgs(target: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "synthetic_pmgs"
    shutil.copytree(source, target)

    pdf_path = target / "REFERENCE" / "IPC_TEIGI" / "G06F3-048.pdf"
    pdf_path.parent.mkdir(parents=True)
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Synthetic IPC definition G06F3/048")
    document.set_metadata({})
    document.save(pdf_path, no_new_id=True, reproducible=True)
    document.close()
    return target


@pytest.fixture
def synthetic_pmgs(tmp_path: Path) -> Path:
    return _copy_synthetic_pmgs(tmp_path / "JPPM2099001")


@pytest.fixture(scope="session")
def synthetic_database(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("synthetic-store")
    source = _copy_synthetic_pmgs(root / "JPPM2099001")
    database = root / "pmgs-reference.sqlite"
    build_database(source, "JPPM2099001", database)
    return database
