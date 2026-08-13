from __future__ import annotations

import errno
import json
import os
import sqlite3
from pathlib import Path

import pytest
from lxml import etree

import pmgs_reference.ingest.build as build_module
import pmgs_reference.ingest.inventory as inventory_module
from pmgs_reference.cli import main
from pmgs_reference.ingest.build import BuildError, build_database
from pmgs_reference.ingest.database import normalize_version_indicator
from pmgs_reference.ingest.inventory import build_inventory
from pmgs_reference.validation import validate_database


def _scalar(connection: sqlite3.Connection, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.parametrize("value", ["(2021.01", "2021.01)"])
def test_ipc_version_indicator_rejects_unbalanced_parentheses(value: str) -> None:
    with pytest.raises(ValueError, match="parentheses must be balanced"):
        normalize_version_indicator(value)


def test_build_rejects_unbalanced_ipc_version_indicator(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    ipc_file = synthetic_pmgs / "IPC" / "IPC8U_TEXT" / "ipc8U_G_20260101.csv"
    original = ipc_file.read_text(encoding="utf-8")
    ipc_file.write_text(
        original.replace(",(2021.01),", ",(2021.01,", 1),
        encoding="utf-8",
    )

    with pytest.raises(BuildError, match="source processing failed"):
        build_database(synthetic_pmgs, "JPPM2099001", tmp_path / "invalid-version.sqlite")


def test_build_rejects_unbalanced_ipc_amendment_version(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    amendment = synthetic_pmgs / "IPC_KAISEI" / "Kaisei202101.html"
    original = amendment.read_text(encoding="utf-8")
    amendment.write_text(
        original.replace("<td>2021.01</td>", "<td>(2021.01</td>", 1),
        encoding="utf-8",
    )

    with pytest.raises(BuildError, match="build_errors=1"):
        build_database(
            synthetic_pmgs,
            "JPPM2099001",
            tmp_path / "invalid-amendment-version.sqlite",
        )


def test_ingest_preserves_more_than_800_synthetic_fi_amendment_relations(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    amendment = synthetic_pmgs / "FI" / "FI_KAISEI_DOC" / "G06F.xml"
    tree = etree.parse(str(amendment))
    root = tree.getroot()
    for index in range(805):
        element = etree.SubElement(root, "infor")
        etree.SubElement(element, "FI", attr="chg").text = "G06F   3/   048"
        etree.SubElement(element, "oldtitle").text = "Synthetic paging source"
        etree.SubElement(element, "newtitle").text = f"Synthetic paging target {index}"
        etree.SubElement(element, "trans").text = f"Z99Z {index:04d}/99"
        etree.SubElement(element, "date").text = "2026-01-01"
    tree.write(str(amendment), encoding="UTF-8", xml_declaration=True)

    database = tmp_path / "many-relations.sqlite"
    build_database(synthetic_pmgs, "JPPM2099001", database)
    validation = validate_database(database)
    connection = sqlite3.connect(database)
    try:
        relation_count = _scalar(
            connection,
            "SELECT COUNT(*) FROM relation r JOIN concept source "
            "ON source.concept_id = r.from_concept_id "
            "WHERE source.scheme = 'fi' AND source.normalized_code = 'G06F3/048' "
            "AND r.kind = 'amended_to'",
        )
        reference_only = _scalar(
            connection,
            "SELECT COUNT(*) FROM concept WHERE record_status = 'reference_only'",
        )
    finally:
        connection.close()

    assert validation.valid is True
    assert relation_count > 800
    assert reference_only > 800


def test_build_creates_complete_queryable_synthetic_database(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    report_path = tmp_path / "build-report.json"

    result = build_database(
        synthetic_pmgs,
        release_id="JPPM2099001",
        output_path=database_path,
        report_path=report_path,
    )

    assert database_path.exists()
    assert not database_path.with_name(f".{database_path.name}.tmp").exists()
    assert result.release_id == "JPPM2099001"
    assert result.schema_version == "2.0"
    assert result.reference_date == "2026-01-01"
    assert result.source_file_count == 26
    assert result.error_count == 0
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["database_sha256"] == result.database_sha256

    with sqlite3.connect(database_path) as connection:
        assert _scalar(connection, "SELECT COUNT(*) FROM source_file") == 26
        assert _scalar(connection, "SELECT COUNT(*) FROM source_record") >= 25
        assert _scalar(connection, "SELECT COUNT(*) FROM concept") >= 10
        assert _scalar(connection, "SELECT COUNT(*) FROM document") >= 8
        assert _scalar(connection, "SELECT COUNT(*) FROM document_text") >= 8
        assert _scalar(connection, "SELECT COUNT(*) FROM relation") >= 5
        rows = connection.execute(
            "SELECT scheme, edition, normalized_code FROM concept "
            "WHERE normalized_code = 'G06F3/048' ORDER BY scheme, edition"
        ).fetchall()
        assert ("fi", "", "G06F3/048") in rows
        assert ("ipc", "8U", "G06F3/048") in rows
        assert _scalar(connection, "SELECT COUNT(*) FROM concept_revision") > 10
        assert (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM concept WHERE record_status = 'reference_only'",
            )
            == 4
        )
        assert (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM concept WHERE scheme = 'fterm' AND concept_type = 'theme'",
            )
            == 1
        )
        assert (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM concept WHERE scheme = 'fterm' AND concept_type = 'term'",
            )
            == 2
        )
        assert (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM concept_text_fts WHERE concept_text_fts MATCH 'Synthetic'",
            )
            > 0
        )
        assert (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM document_text_fts WHERE document_text_fts MATCH 'Synthetic'",
            )
            > 0
        )
        locator_plan = " ".join(
            str(row[3])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT text FROM document_text "
                "WHERE document_id = ? AND source_locator = ?",
                ("missing", "page:1"),
            )
        )
        assert "document_text_locator_idx" in locator_plan


def test_validate_database_checks_integrity_and_expected_counts(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    build_database(synthetic_pmgs, "JPPM2099001", database_path)

    validation = validate_database(database_path)

    assert validation.valid is True
    assert validation.integrity_check == "ok"
    assert validation.foreign_key_error_count == 0
    assert validation.build_error_count == 0
    assert validation.counts["source_file"] == 26
    assert validation.regression_checks == {}
    assert validation.database_file == "pmgs-reference.sqlite"
    assert len(validation.database_sha256) == 64


def test_build_and_validate_cli_emit_machine_readable_results(
    synthetic_pmgs: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    assert (
        main(
            [
                "build",
                str(synthetic_pmgs),
                "--release",
                "JPPM2099001",
                "--output",
                str(database_path),
            ]
        )
        == 0
    )
    build_output = json.loads(capsys.readouterr().out)
    assert build_output["source_file_count"] == 26

    assert main(["validate", str(database_path)]) == 0
    validation_output = json.loads(capsys.readouterr().out)
    assert validation_output["valid"] is True


def test_validate_cli_writes_report(
    synthetic_pmgs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    report_path = tmp_path / "validation-report.json"
    build_database(synthetic_pmgs, "JPPM2099001", database_path)

    assert main(["validate", str(database_path), "--report", str(report_path)]) == 0

    capsys.readouterr()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["valid"] is True
    assert payload["database_file"] == database_path.name
    assert str(tmp_path) not in report_path.read_text(encoding="utf-8")


def test_build_refuses_to_overwrite_an_existing_database(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    build_database(synthetic_pmgs, "JPPM2099001", database_path)
    before = database_path.read_bytes()

    with pytest.raises(FileExistsError, match="already exists"):
        build_database(synthetic_pmgs, "JPPM2099001", database_path)

    assert database_path.read_bytes() == before


def test_build_accepts_a_precomputed_inventory(synthetic_pmgs: Path, tmp_path: Path) -> None:
    inventory = build_inventory(synthetic_pmgs)
    result = build_database(
        synthetic_pmgs,
        "JPPM2099001",
        tmp_path / "pmgs-reference.sqlite",
        inventory=inventory,
    )

    assert result.source_manifest_sha256 == inventory.logical_sha256


def test_build_records_revisions_reference_only_links_and_attribution(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    result = build_database(synthetic_pmgs, "JPPM2099001", database_path)

    with sqlite3.connect(database_path) as connection:
        versions = connection.execute(
            """
            SELECT cr.version_indicator, cr.valid_from, cr.valid_to
            FROM concept_revision cr JOIN concept c USING(concept_id)
            WHERE c.scheme = 'ipc' AND c.edition = '8U' AND c.normalized_code = 'G06F3/048'
            ORDER BY cr.version_indicator
            """
        ).fetchall()
        assert versions == [
            ("2006.01", "2006-01-01", "2020-12-31"),
            ("2021.01", "2021-01-01", "9999-12-31"),
        ]
        active = _scalar(
            connection,
            """
            SELECT COUNT(*) FROM concept_revision cr JOIN concept c USING(concept_id)
            JOIN release r ON r.release_id = c.release_id
            WHERE c.scheme = 'ipc' AND c.edition = '8U'
              AND c.normalized_code = 'G06F3/048'
              AND (cr.valid_from IS NULL OR cr.valid_from <= r.reference_date)
              AND (cr.valid_to IS NULL OR cr.valid_to >= r.reference_date)
            """,
        )
        assert active == 1
        assert _scalar(connection, "SELECT COUNT(*) FROM revision_relation") == 1
        assert _scalar(connection, "SELECT COUNT(*) FROM document_revision_link") == 2
        fi_document_codes = connection.execute(
            "SELECT c.normalized_code FROM document_link dl "
            "JOIN concept c USING(concept_id) WHERE dl.kind = 'fi_amendment' "
            "ORDER BY c.normalized_code"
        ).fetchall()
        assert fi_document_codes == [("G06F3/040",), ("G06F3/048",)]
        assert (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM concept WHERE scheme = 'fi' "
                "AND record_status = 'reference_only'",
            )
            == 2
        )
        release_source = connection.execute(
            "SELECT owner, original_url, attribution FROM release_source"
        ).fetchone()
        assert release_source == (
            "JPO",
            "https://www.jpo.go.jp/system/laws/sesaku/data/download.html",
            "Copyright (C) TEST 2026",
        )
        assert (
            _scalar(
                connection,
                """
                SELECT COUNT(*) FROM source_file sf
                WHERE sf.record_count != (
                    SELECT COUNT(*) FROM source_record sr WHERE sr.file_id = sf.file_id
                )
                """,
            )
            == 0
        )
        assert (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM build_issue WHERE code = 'HTML_RECOVERY_USED'",
            )
            == 1
        )
    assert result.warning_count >= 1


def test_build_detects_source_mutation_and_leaves_no_output(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    original = build_module.process_sources

    def mutate_after_processing(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        path = synthetic_pmgs / "JUDGE" / "judge_20260101.csv"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    monkeypatch.setattr(build_module, "process_sources", mutate_after_processing)

    with pytest.raises(BuildError, match="changed during database construction"):
        build_database(synthetic_pmgs, "JPPM2099001", database_path)

    assert not database_path.exists()
    assert not list(tmp_path.glob(f".{database_path.name}-*.tmp"))


def test_build_rejects_ambiguous_reference_dates(synthetic_pmgs: Path, tmp_path: Path) -> None:
    source = next((synthetic_pmgs / "FI" / "FI").glob("*.csv"))
    source.rename(source.with_name(source.name.replace("20260101", "20260102")))

    with pytest.raises(BuildError, match="exactly one valid classification CSV reference date"):
        build_database(synthetic_pmgs, "JPPM2099001", tmp_path / "ambiguous.sqlite")


def test_build_ignores_non_classification_csv_dates(synthetic_pmgs: Path, tmp_path: Path) -> None:
    source = synthetic_pmgs / "JUDGE" / "judge_20260101.csv"
    source.rename(source.with_name("judge_20260102.csv"))

    result = build_database(synthetic_pmgs, "JPPM2099001", tmp_path / "judge-date.sqlite")

    assert result.reference_date == "2026-01-01"


def test_build_uses_the_unique_valid_date_when_one_csv_filename_is_malformed(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    source = synthetic_pmgs / "FTERM" / "FTERM_E" / "ftermE_4C_20260101.csv"
    source.rename(source.with_name("ftermE_4C_202601011.csv"))

    result = build_database(synthetic_pmgs, "JPPM2099001", tmp_path / "malformed-date.sqlite")

    assert result.reference_date == "2026-01-01"


def test_english_fterm_text_does_not_override_japanese_hierarchy(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    english = synthetic_pmgs / "FTERM" / "FTERM_E" / "ftermE_4C_20260101.csv"
    english.write_text(
        english.read_text(encoding="utf-8").replace(
            '4C083AA01,       2, 1,"Synthetic term"',
            '4C083AA01,       2, 0,"Synthetic term"',
        ),
        encoding="utf-8",
    )
    database = tmp_path / "english-depth.sqlite"

    result = build_database(synthetic_pmgs, "JPPM2099001", database)

    assert result.error_count == 0
    assert result.warning_count >= 1
    with sqlite3.connect(database) as connection:
        level, parent = connection.execute(
            "SELECT cr.level, parent.normalized_code FROM concept child "
            "JOIN concept_revision cr ON cr.concept_id = child.concept_id "
            "JOIN relation r ON r.from_concept_id = child.concept_id AND r.kind = 'parent' "
            "JOIN concept parent ON parent.concept_id = r.to_concept_id "
            "WHERE child.scheme = 'fterm' AND child.normalized_code = '4C083AA01'"
        ).fetchone()
        english_labels = connection.execute(
            "SELECT COUNT(*) FROM concept_text ct JOIN concept_revision cr USING(revision_id) "
            "JOIN concept c USING(concept_id) WHERE c.normalized_code = '4C083AA01' "
            "AND ct.language = 'en' AND ct.kind = 'label'"
        ).fetchone()[0]
        depth_warnings = connection.execute(
            "SELECT COUNT(*) FROM build_issue WHERE code = 'FTERM_TRANSLATION_DEPTH_MISMATCH'"
        ).fetchone()[0]
    assert level == 3
    assert parent == "4C083AA00"
    assert english_labels == 1
    assert depth_warnings == 1


def test_english_fterm_depth_shift_does_not_cascade_into_canonical_parents(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    japanese = synthetic_pmgs / "FTERM" / "FTERM" / "fterm_4C_20260101.csv"
    english = synthetic_pmgs / "FTERM" / "FTERM_E" / "ftermE_4C_20260101.csv"
    with japanese.open("a", encoding="utf-8", newline="") as stream:
        stream.write(
            '4C083AA02,       3, 2,"Synthetic child","A61K8/00"\n'
            '4C083AA03,       4, 3,"Synthetic grandchild","A61K8/00"\n'
            '4C083AA04,       5, 4,"Synthetic deep term","A61K8/00"\n'
            '4C083AA05,       6, 4,"Synthetic deep sibling","A61K8/00"\n'
        )
    with english.open("a", encoding="utf-8", newline="") as stream:
        stream.write(
            '4C083AA02,       3, 1,"Synthetic child","A61K8/00"\n'
            '4C083AA03,       4, 2,"Synthetic grandchild","A61K8/00"\n'
            '4C083AA04,       5, 3,"Synthetic deep term","A61K8/00"\n'
            '4C083AA05,       6, 4,"Synthetic deep sibling","A61K8/00"\n'
        )
    database = tmp_path / "english-depth-cascade.sqlite"

    result = build_database(synthetic_pmgs, "JPPM2099001", database)

    assert result.error_count == 0
    with sqlite3.connect(database) as connection:
        parents = dict(
            connection.execute(
                "SELECT child.normalized_code, parent.normalized_code FROM concept child "
                "JOIN relation r ON r.from_concept_id = child.concept_id AND r.kind = 'parent' "
                "JOIN concept parent ON parent.concept_id = r.to_concept_id "
                "WHERE child.normalized_code BETWEEN '4C083AA02' AND '4C083AA05'"
            ).fetchall()
        )
        warning_count = connection.execute(
            "SELECT COUNT(*) FROM build_issue WHERE code = 'FTERM_TRANSLATION_DEPTH_MISMATCH'"
        ).fetchone()[0]
    assert parents == {
        "4C083AA02": "4C083AA01",
        "4C083AA03": "4C083AA02",
        "4C083AA04": "4C083AA03",
        "4C083AA05": "4C083AA03",
    }
    assert warning_count == 3


@pytest.mark.parametrize(
    ("replacement", "error_code"),
    [
        (
            '4C083AA99,      99, 1,"Synthetic term"',
            "FTERM_TRANSLATION_CONCEPT_MISSING",
        ),
        (
            '4C083AA01,      99, 1,"Synthetic term"',
            "FTERM_TRANSLATION_SEQUENCE_MISMATCH",
        ),
    ],
)
def test_build_rejects_unmatched_english_fterm_structure(
    synthetic_pmgs: Path, tmp_path: Path, replacement: str, error_code: str
) -> None:
    english = synthetic_pmgs / "FTERM" / "FTERM_E" / "ftermE_4C_20260101.csv"
    english.write_text(
        english.read_text(encoding="utf-8").replace(
            '4C083AA01,       2, 1,"Synthetic term"',
            replacement,
        ),
        encoding="utf-8",
    )
    database = tmp_path / f"{error_code.lower()}.sqlite"

    with pytest.raises(BuildError, match="build_errors=1"):
        build_database(synthetic_pmgs, "JPPM2099001", database)

    assert not database.exists()


@pytest.mark.parametrize(
    ("english_row", "error_code"),
    [
        (
            '9Z999,4,9Z,0,       2,"G99Z9/99","Unknown theme","fixture"',
            "THEME_TRANSLATION_CONCEPT_MISSING",
        ),
    ],
)
def test_build_rejects_unmatched_english_theme_structure(
    synthetic_pmgs: Path, tmp_path: Path, english_row: str, error_code: str
) -> None:
    english = synthetic_pmgs / "FTERM" / "THEME_E" / "themeE_20260101.csv"
    if english_row.startswith("4C083,"):
        rows = english.read_text(encoding="utf-8").splitlines()
        rows[-1] = english_row
        english.write_text("\n".join(rows) + "\n", encoding="utf-8")
    else:
        with english.open("a", encoding="utf-8", newline="") as stream:
            stream.write(english_row + "\n")
    database = tmp_path / f"{error_code.lower()}.sqlite"

    with pytest.raises(BuildError, match="build_errors=1"):
        build_database(synthetic_pmgs, "JPPM2099001", database)

    assert not database.exists()


def test_build_warns_on_english_theme_sequence_difference(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    english = synthetic_pmgs / "FTERM" / "THEME_E" / "themeE_20260101.csv"
    rows = english.read_text(encoding="utf-8").splitlines()
    rows[-1] = '4C083,99,4C,0,       2,"A61K8/00","Synthetic cosmetics theme","fixture"'
    english.write_text("\n".join(rows) + "\n", encoding="utf-8")
    database = tmp_path / "theme-translation-sequence.sqlite"

    result = build_database(synthetic_pmgs, "JPPM2099001", database)

    assert result.error_count == 0
    with sqlite3.connect(database) as connection:
        canonical_sequence = connection.execute(
            "SELECT cr.sequence_number FROM concept_revision cr "
            "JOIN concept c USING(concept_id) WHERE c.scheme = 'fterm' "
            "AND c.normalized_code = '4C083'"
        ).fetchone()[0]
        warnings = connection.execute(
            "SELECT COUNT(*) FROM build_issue WHERE code = 'THEME_TRANSLATION_SEQUENCE_MISMATCH'"
        ).fetchone()[0]
        english_labels = connection.execute(
            "SELECT COUNT(*) FROM concept_text ct JOIN concept_revision cr USING(revision_id) "
            "JOIN concept c USING(concept_id) WHERE c.scheme = 'fterm' "
            "AND c.normalized_code = '4C083' AND ct.language = 'en' AND ct.kind = 'label'"
        ).fetchone()[0]
        theme_source_counts = connection.execute(
            "SELECT sf.record_count, COUNT(sr.file_id) FROM source_file sf "
            "LEFT JOIN source_record sr ON sr.file_id = sf.file_id "
            "WHERE sf.relative_path LIKE 'FTERM/THEME_E/%' GROUP BY sf.file_id"
        ).fetchone()
    assert canonical_sequence == 3
    assert warnings == 1
    assert english_labels == 1
    assert theme_source_counts == (1, 1)


def test_build_keeps_ipc_text_sequence_on_each_text_row(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    ipc_file = synthetic_pmgs / "IPC" / "IPC8U_TEXT" / "ipc8U_G_20260101.csv"
    with ipc_file.open("a", encoding="utf-8", newline="") as stream:
        stream.write(
            "G06F   3/048    ,(2021.01),99, 2,07,1, ,20210101,99991231, 0,"
            '"Synthetic secondary text"\n'
        )

    database = tmp_path / "ipc-text-sequence.sqlite"
    result = build_database(synthetic_pmgs, "JPPM2099001", database)

    assert result.error_count == 0
    with sqlite3.connect(database) as connection:
        revision = connection.execute(
            "SELECT cr.revision_id, cr.sequence_number FROM concept_revision cr "
            "JOIN concept c USING(concept_id) WHERE c.scheme = 'ipc' AND c.edition = '8U' "
            "AND c.normalized_code = 'G06F3/048' AND cr.version_indicator = '2021.01'"
        ).fetchone()
        assert revision is not None
        text_sequences = connection.execute(
            "SELECT sequence_number FROM concept_text WHERE revision_id = ? ORDER BY text_id",
            (revision[0],),
        ).fetchall()
    assert revision[1] is None
    assert text_sequences == [(2,), (99,)]


@pytest.mark.parametrize("invalid_sequence", ["", "invalid", "0"])
def test_build_rejects_invalid_ipc_text_sequence(
    synthetic_pmgs: Path, tmp_path: Path, invalid_sequence: str
) -> None:
    ipc_file = synthetic_pmgs / "IPC" / "IPC8U_TEXT" / "ipc8U_G_20260101.csv"
    rows = ipc_file.read_text(encoding="utf-8").splitlines()
    rows[0] = rows[0].replace(", 1, 1,", f",{invalid_sequence}, 1,")
    ipc_file.write_text("\n".join(rows) + "\n", encoding="utf-8")

    with pytest.raises(BuildError, match="build_errors=1"):
        build_database(synthetic_pmgs, "JPPM2099001", tmp_path / "invalid-sequence.sqlite")


def test_build_rejects_structural_revision_sequence_conflict(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    fi_file = next((synthetic_pmgs / "FI" / "FI").glob("*.csv"))
    with fi_file.open("a", encoding="utf-8", newline="") as stream:
        stream.write("G06F   3/   048    ,999, ,  ,07\n")

    with pytest.raises(BuildError, match="build_errors=1"):
        build_database(synthetic_pmgs, "JPPM2099001", tmp_path / "sequence-conflict.sqlite")


def test_validator_accepts_repeated_fi_amendment_rows_for_one_semantic_relation(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    amendment = synthetic_pmgs / "FI" / "FI_KAISEI_DOC" / "G06F.xml"
    raw = amendment.read_text(encoding="utf-8")
    repeated = (
        "  <infor>\n"
        '    <FI attr="del">G06F   3/   040</FI>\n'
        "    <oldtitle>Repeated synthetic source</oldtitle>\n"
        "    <newtitle>Repeated synthetic target</newtitle>\n"
        "    <trans>G06F   3/   041</trans>\n"
        "    <date>2026-01-01</date>\n"
        "  </infor>\n"
    )
    amendment.write_text(raw.replace("</data>", repeated * 3 + "</data>"), encoding="utf-8")
    database = tmp_path / "repeated-fi-amendment.sqlite"

    build_database(synthetic_pmgs, "JPPM2099001", database)
    validation = validate_database(database)

    assert validation.valid is True
    assert validation.checks["fi_amendment_relation_coverage"]["actual"] == 0
    with sqlite3.connect(database) as connection:
        semantic_relations = connection.execute(
            "SELECT COUNT(*) FROM relation r JOIN source_file sf "
            "ON sf.file_id = r.source_file_id WHERE r.kind = 'amended_to' "
            "AND sf.data_group = 'FI/FI_KAISEI_DOC'"
        ).fetchone()[0]
    assert semantic_relations == 2


def test_build_rejects_empty_copyright_and_conflicting_duplicate_revision(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    copyright_file = synthetic_pmgs / "COPYRGHT"
    copyright_file.write_text(" \n", encoding="utf-8")
    with pytest.raises(BuildError, match="source processing failed"):
        build_database(synthetic_pmgs, "JPPM2099001", tmp_path / "empty-copyright.sqlite")

    copyright_file.write_text("Copyright (C) TEST 2026\n", encoding="utf-8")
    ipc_file = synthetic_pmgs / "IPC" / "IPC8U_TEXT" / "ipc8U_G_20260101.csv"
    with ipc_file.open("a", encoding="utf-8", newline="") as stream:
        stream.write(
            "G06F   3/048    ,(2021.01), 4, 1,07,1, ,20220101,99991231, 0,"
            '"Conflicting synthetic revision"\n'
        )
    with pytest.raises(BuildError, match="build_errors=1"):
        build_database(synthetic_pmgs, "JPPM2099001", tmp_path / "conflict.sqlite")


def test_build_rejects_duplicate_copyright_and_unresolved_ipc_amendment(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    duplicate = synthetic_pmgs / "EXTRA" / "COPYRGHT"
    duplicate.parent.mkdir()
    duplicate.write_text("Copyright (C) TEST 2026\n", encoding="utf-8")
    with pytest.raises(BuildError, match="source processing failed"):
        build_database(synthetic_pmgs, "JPPM2099001", tmp_path / "duplicate.sqlite")

    duplicate.unlink()
    amendment = synthetic_pmgs / "IPC_KAISEI" / "Kaisei202101.html"
    amendment.write_text(
        amendment.read_text(encoding="utf-8").replace(
            "<td>G06F3/048</td><td>2021.01</td>",
            "<td>G99Z9/999</td><td>2021.01</td>",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(BuildError, match="build_errors=1"):
        build_database(synthetic_pmgs, "JPPM2099001", tmp_path / "unresolved.sqlite")


def test_build_rejects_unresolved_fi_amendment_document_link(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    link_file = next((synthetic_pmgs / "FI" / "FI_KAISEI_LINK").glob("*.csv"))
    link_file.write_text("H99H,Missing synthetic revision document\n", encoding="utf-8")

    with pytest.raises(BuildError, match="build_errors=1"):
        build_database(synthetic_pmgs, "JPPM2099001", tmp_path / "missing-fi-link.sqlite")


def test_build_accepts_the_real_ipc_amendment_td_header_shape(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    amendment = synthetic_pmgs / "IPC_KAISEI" / "Kaisei202101.html"
    amendment.write_text(
        amendment.read_text(encoding="utf-8").replace(
            "<tr><th>Old IPC</th><th>Effective</th><th>New IPC</th><th>Effective</th></tr>",
            "<tr><td>旧ＩＰＣ</td><td>分類の発効日</td><td>新ＩＰＣ</td><td>分類の発効日</td></tr>",
        ),
        encoding="utf-8",
    )

    database = tmp_path / "real-header.sqlite"
    build_database(synthetic_pmgs, "JPPM2099001", database)
    validation = validate_database(database)

    assert validation.valid is True
    assert validation.regression_checks == {}


@pytest.mark.parametrize(
    "replacement",
    [
        "<tr><td>G06F3/048</td><td>2006.01</td><td>G06F3/048</td></tr>",
        (
            "<tr><td>G06F3/048</td><td>2006.01</td><td>G06F3/048</td>"
            "<td>2021.01</td><td>unexpected</td></tr>"
        ),
    ],
)
def test_build_rejects_ipc_amendment_rows_with_unexpected_column_count(
    synthetic_pmgs: Path, tmp_path: Path, replacement: str
) -> None:
    amendment = synthetic_pmgs / "IPC_KAISEI" / "Kaisei202101.html"
    original_row = "<tr><td>G06F3/048</td><td>2006.01</td><td>G06F3/048</td><td>2021.01</td></tr>"
    amendment.write_text(
        amendment.read_text(encoding="utf-8").replace(original_row, replacement),
        encoding="utf-8",
    )

    with pytest.raises(BuildError, match="build_errors=1"):
        build_database(
            synthetic_pmgs,
            "JPPM2099001",
            tmp_path / "invalid-ipc-amendment-shape.sqlite",
        )


def test_build_retains_empty_html_table_rows_as_source_records(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    html_file = next((synthetic_pmgs / "FTERM" / "ADD_CODE").glob("*.html"))
    html_file.write_text(
        html_file.read_text(encoding="utf-8").replace(
            "</table>", "<tr><td> </td><td></td></tr></table>"
        ),
        encoding="utf-8",
    )
    database = tmp_path / "empty-html-row.sqlite"

    build_database(synthetic_pmgs, "JPPM2099001", database)

    with sqlite3.connect(database) as connection:
        empty_rows = connection.execute(
            "SELECT COUNT(*) FROM source_record WHERE record_kind = 'html-empty-row'"
        ).fetchone()[0]
    assert empty_rows == 1


def test_inventory_rejects_source_links_and_oversized_files(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("not PMGS data", encoding="utf-8")
    linked = synthetic_pmgs / "JUDGE" / "linked_20260101.csv"
    try:
        linked.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")
    with pytest.raises(ValueError, match="link or reparse point"):
        build_inventory(synthetic_pmgs)

    linked.unlink()
    oversized = synthetic_pmgs / "JUDGE" / "oversized_20260101.csv"
    oversized.write_bytes(b"x" * 33)
    monkeypatch.setattr(inventory_module, "MAX_SOURCE_FILE_BYTES", 32)
    inventory = build_inventory(synthetic_pmgs)
    entry = next(item for item in inventory.entries if item.relative_path.endswith(oversized.name))

    assert entry.status == "failed"
    assert entry.parser == "resource-limit"


def test_build_rejects_linked_source_root(synthetic_pmgs: Path, tmp_path: Path) -> None:
    linked_root = tmp_path / "linked-pmgs"
    try:
        linked_root.symlink_to(synthetic_pmgs, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    output_path = tmp_path / "linked-source.sqlite"
    with pytest.raises(ValueError, match="link or reparse point"):
        build_database(linked_root, "JPPM2099001", output_path)

    assert not output_path.exists()


@pytest.mark.parametrize("missing_object", ["source_record", "concept_text_fts"])
def test_validator_fails_closed_for_missing_semantic_or_fts_table(
    synthetic_pmgs: Path, tmp_path: Path, missing_object: str
) -> None:
    database_path = tmp_path / f"missing-{missing_object}.sqlite"
    build_database(synthetic_pmgs, "JPPM2099001", database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(f'DROP TABLE "{missing_object}"')

    validation = validate_database(database_path)

    assert validation.valid is False
    assert validation.checks["required_tables"]["match"] is False


def test_validator_rejects_missing_release_source_and_overlapping_active_revision(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    missing_source = tmp_path / "missing-release-source.sqlite"
    build_database(synthetic_pmgs, "JPPM2099001", missing_source)
    with sqlite3.connect(missing_source) as connection:
        connection.execute("DELETE FROM release_source")
    validation = validate_database(missing_source)
    assert validation.valid is False
    assert validation.checks["release_source_COPYRGHT_lineage"]["match"] is False

    overlapping = tmp_path / "overlapping.sqlite"
    build_database(synthetic_pmgs, "JPPM2099001", overlapping)
    with sqlite3.connect(overlapping) as connection:
        concept_id, source_file_id = connection.execute(
            """
            SELECT c.concept_id, c.source_file_id FROM concept c
            WHERE c.scheme = 'ipc' AND c.edition = '8U'
              AND c.normalized_code = 'G06F3/048'
            """
        ).fetchone()
        connection.execute(
            """
            INSERT INTO concept_revision(
                concept_id, version_indicator, valid_from, valid_to, level,
                sequence_number, source_file_id, source_locator
            ) VALUES (?, '2025.01', '2025-01-01', '9999-12-31', 7, 99, ?, 'test')
            """,
            (concept_id, source_file_id),
        )
    validation = validate_database(overlapping)
    assert validation.valid is False
    assert validation.checks["active_at_reference_date_unique"]["actual"] == 1
    assert validation.checks["ipc_revision_sequence_is_text_scoped"]["actual"] == 1


@pytest.mark.parametrize(
    ("target", "check_name"),
    [
        ("source_record", "source_file_record_counts"),
        ("concept_text_fts", "concept_text_fts_parity"),
        ("document_text_fts", "document_text_fts_parity"),
    ],
)
def test_validator_rejects_deleted_source_or_fts_rows(
    synthetic_pmgs: Path, tmp_path: Path, target: str, check_name: str
) -> None:
    database_path = tmp_path / f"deleted-{target}.sqlite"
    build_database(synthetic_pmgs, "JPPM2099001", database_path)
    with sqlite3.connect(database_path) as connection:
        if target == "source_record":
            connection.execute("DELETE FROM source_record")
        else:
            connection.execute(
                f'DELETE FROM "{target}" WHERE rowid = (SELECT MIN(rowid) FROM "{target}")'
            )

    validation = validate_database(database_path)

    assert validation.valid is False
    assert validation.checks[check_name]["match"] is False


@pytest.mark.parametrize(
    ("delete_sql", "check_name"),
    [
        (
            "DELETE FROM revision_relation WHERE revision_relation_id = "
            "(SELECT MIN(revision_relation_id) FROM revision_relation)",
            "ipc_amendment_relation_coverage",
        ),
        (
            "DELETE FROM document_revision_link WHERE (document_id, revision_id, kind) = "
            "(SELECT document_id, revision_id, kind FROM document_revision_link "
            "ORDER BY document_id, revision_id, kind LIMIT 1)",
            "ipc_amendment_document_link_coverage",
        ),
        (
            "DELETE FROM relation WHERE relation_id = (SELECT MIN(r.relation_id) "
            "FROM relation r JOIN source_file sf ON sf.file_id = r.source_file_id "
            "WHERE sf.data_group = 'FI/FI_KAISEI_DOC' AND r.kind = 'amended_to')",
            "fi_amendment_relation_coverage",
        ),
        (
            "DELETE FROM document_link WHERE (document_id, concept_id, kind) = "
            "(SELECT dl.document_id, dl.concept_id, dl.kind FROM document_link dl "
            "JOIN source_file sf ON sf.file_id = dl.source_file_id "
            "WHERE sf.data_group = 'FI/FI_KAISEI_DOC' AND dl.kind = 'fi_amendment' "
            "ORDER BY dl.document_id, dl.concept_id LIMIT 1)",
            "fi_amendment_document_link_coverage",
        ),
    ],
)
def test_validator_rejects_missing_amendment_relation_or_document_link(
    synthetic_pmgs: Path, tmp_path: Path, delete_sql: str, check_name: str
) -> None:
    database_path = tmp_path / f"missing-{check_name}.sqlite"
    build_database(synthetic_pmgs, "JPPM2099001", database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(delete_sql)

    validation = validate_database(database_path)

    assert validation.valid is False
    assert validation.checks[check_name]["match"] is False


def test_logical_digest_is_stable_across_independent_builds(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    first = build_database(synthetic_pmgs, "JPPM2099001", tmp_path / "first.sqlite")
    second = build_database(synthetic_pmgs, "JPPM2099001", tmp_path / "second.sqlite")

    assert first.logical_digest == second.logical_digest
    assert validate_database(tmp_path / "first.sqlite").logical_digest == first.logical_digest


def test_build_falls_back_when_hard_links_are_unavailable(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"

    def unsupported_link(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EXDEV, "simulated hard-link limitation")

    monkeypatch.setattr(build_module, "_WINDOWS", True)
    monkeypatch.setattr(build_module.os, "link", unsupported_link)

    result = build_database(synthetic_pmgs, "JPPM2099001", database_path)

    assert validate_database(database_path).valid is True
    assert result.database_sha256 == validate_database(database_path).database_sha256
    assert not list(tmp_path.glob(f".{database_path.name}-*.tmp"))


def test_build_cleans_temporary_files_when_fallback_promotion_fails(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"

    def unsupported_link(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EXDEV, "simulated hard-link limitation")

    def failed_rename(_source: Path, _destination: Path) -> None:
        raise OSError("simulated promotion failure")

    monkeypatch.setattr(build_module, "_WINDOWS", True)
    monkeypatch.setattr(build_module.os, "link", unsupported_link)
    monkeypatch.setattr(build_module.os, "rename", failed_rename)

    with pytest.raises(OSError, match="simulated promotion failure"):
        build_database(synthetic_pmgs, "JPPM2099001", database_path)

    assert not database_path.exists()
    assert not list(tmp_path.glob(f".{database_path.name}-*.tmp"))


def test_build_fallback_does_not_overwrite_a_racing_destination(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    existing_bytes = b"concurrent writer"

    def racing_link(_source: Path, destination: Path) -> None:
        destination.write_bytes(existing_bytes)
        raise OSError(errno.EXDEV, "simulated hard-link limitation")

    def no_replace_rename(_source: Path, destination: Path) -> None:
        assert destination.read_bytes() == existing_bytes
        raise FileExistsError(errno.EEXIST, "simulated Windows no-replace rename")

    monkeypatch.setattr(build_module, "_WINDOWS", True)
    monkeypatch.setattr(build_module.os, "link", racing_link)
    monkeypatch.setattr(build_module.os, "rename", no_replace_rename)

    with pytest.raises(FileExistsError, match="already exists"):
        build_database(synthetic_pmgs, "JPPM2099001", database_path)

    assert database_path.read_bytes() == existing_bytes
    assert not list(tmp_path.glob(f".{database_path.name}-*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows no-replace rename contract")
def test_windows_fallback_uses_real_no_replace_rename(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    existing_bytes = b"concurrent Windows writer"

    def racing_link(_source: Path, destination: Path) -> None:
        destination.write_bytes(existing_bytes)
        raise OSError(errno.EXDEV, "simulated hard-link limitation")

    monkeypatch.setattr(build_module, "_WINDOWS", True)
    monkeypatch.setattr(build_module.os, "link", racing_link)

    with pytest.raises(FileExistsError, match="already exists"):
        build_database(synthetic_pmgs, "JPPM2099001", database_path)

    assert database_path.read_bytes() == existing_bytes
    assert not list(tmp_path.glob(f".{database_path.name}-*.tmp"))


def test_build_fails_closed_without_hard_links_on_non_windows(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    rename_called = False

    def unsupported_link(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EXDEV, "simulated hard-link limitation")

    def unexpected_rename(_source: Path, _destination: Path) -> None:
        nonlocal rename_called
        rename_called = True

    monkeypatch.setattr(build_module, "_WINDOWS", False)
    monkeypatch.setattr(build_module.os, "link", unsupported_link)
    monkeypatch.setattr(build_module.os, "rename", unexpected_rename)

    with pytest.raises(OSError, match="simulated hard-link limitation"):
        build_database(synthetic_pmgs, "JPPM2099001", database_path)

    assert rename_called is False
    assert not database_path.exists()
    assert not list(tmp_path.glob(f".{database_path.name}-*.tmp"))
