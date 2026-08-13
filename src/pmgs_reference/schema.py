"""SQLite schema for the versioned PMGS canonical store."""

from __future__ import annotations

SCHEMA_VERSION = "2.0"
APPLICATION_ID = 0x504D4753  # PMGS
DATABASE_USER_VERSION = 2

SCHEMA_SQL = f"""
PRAGMA application_id = {APPLICATION_ID};
PRAGMA user_version = {DATABASE_USER_VERSION};

CREATE TABLE release (
    release_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    reference_date TEXT NOT NULL CHECK (
        reference_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
        AND date(reference_date) = reference_date
    ),
    source_manifest_sha256 TEXT NOT NULL,
    source_file_count INTEGER NOT NULL CHECK (source_file_count >= 0),
    source_total_bytes INTEGER NOT NULL CHECK (source_total_bytes >= 0)
) STRICT;

CREATE TABLE source_file (
    file_id INTEGER PRIMARY KEY,
    release_id TEXT NOT NULL REFERENCES release(release_id),
    source_id TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    sha256 TEXT NOT NULL,
    file_type TEXT NOT NULL,
    encoding TEXT,
    data_group TEXT NOT NULL,
    parser TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('parsed', 'retained', 'failed')),
    error TEXT,
    record_count INTEGER NOT NULL DEFAULT 0 CHECK (record_count >= 0),
    UNIQUE (release_id, relative_path)
) STRICT;

CREATE TABLE source_record (
    file_id INTEGER NOT NULL REFERENCES source_file(file_id),
    record_number INTEGER NOT NULL CHECK (record_number > 0),
    record_kind TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    PRIMARY KEY (file_id, record_number)
) WITHOUT ROWID, STRICT;

CREATE TRIGGER source_record_count_insert
AFTER INSERT ON source_record
BEGIN
    UPDATE source_file SET record_count = record_count + 1 WHERE file_id = NEW.file_id;
END;

CREATE TABLE release_source (
    release_id TEXT PRIMARY KEY REFERENCES release(release_id),
    owner TEXT NOT NULL CHECK (owner <> ''),
    original_url TEXT NOT NULL CHECK (original_url <> ''),
    attribution TEXT NOT NULL CHECK (attribution = trim(attribution) AND attribution <> ''),
    source_file_id INTEGER NOT NULL REFERENCES source_file(file_id),
    source_locator TEXT NOT NULL CHECK (source_locator <> '')
) STRICT;

CREATE TABLE concept (
    concept_id INTEGER PRIMARY KEY,
    release_id TEXT NOT NULL REFERENCES release(release_id),
    scheme TEXT NOT NULL CHECK (scheme IN ('fi', 'fterm', 'ipc')),
    edition TEXT NOT NULL DEFAULT '',
    code TEXT NOT NULL,
    normalized_code TEXT NOT NULL,
    concept_type TEXT NOT NULL,
    record_status TEXT NOT NULL CHECK (record_status IN ('canonical', 'reference_only')),
    source_file_id INTEGER NOT NULL REFERENCES source_file(file_id),
    source_locator TEXT NOT NULL CHECK (source_locator <> ''),
    UNIQUE (release_id, scheme, edition, normalized_code)
) STRICT;

CREATE TABLE concept_revision (
    revision_id INTEGER PRIMARY KEY,
    concept_id INTEGER NOT NULL REFERENCES concept(concept_id),
    version_indicator TEXT NOT NULL DEFAULT '' CHECK (
        version_indicator = '' OR version_indicator GLOB '[0-9][0-9][0-9][0-9].[0-9][0-9]'
    ),
    valid_from TEXT CHECK (
        valid_from IS NULL OR (
            valid_from GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            AND date(valid_from) = valid_from
        )
    ),
    valid_to TEXT CHECK (
        valid_to IS NULL OR (
            valid_to GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            AND date(valid_to) = valid_to
        )
    ),
    level INTEGER,
    sequence_number INTEGER,
    source_file_id INTEGER NOT NULL REFERENCES source_file(file_id),
    source_locator TEXT NOT NULL CHECK (source_locator <> ''),
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to),
    UNIQUE (concept_id, version_indicator)
) STRICT;

CREATE TABLE concept_text (
    text_id INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES concept_revision(revision_id),
    language TEXT NOT NULL CHECK (language IN ('ja', 'en')),
    kind TEXT NOT NULL,
    sequence_number INTEGER NOT NULL DEFAULT 1,
    text TEXT NOT NULL,
    translation_status TEXT NOT NULL CHECK (
        translation_status IN ('official', 'not_translated', 'unavailable')
    ),
    source_file_id INTEGER NOT NULL REFERENCES source_file(file_id),
    source_locator TEXT NOT NULL CHECK (source_locator <> '')
) STRICT;

CREATE TABLE concept_property (
    property_id INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES concept_revision(revision_id),
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    language TEXT,
    source_file_id INTEGER NOT NULL REFERENCES source_file(file_id),
    source_locator TEXT NOT NULL CHECK (source_locator <> '')
) STRICT;

CREATE TABLE relation (
    relation_id INTEGER PRIMARY KEY,
    from_concept_id INTEGER NOT NULL REFERENCES concept(concept_id),
    to_concept_id INTEGER NOT NULL REFERENCES concept(concept_id),
    kind TEXT NOT NULL,
    source_file_id INTEGER NOT NULL REFERENCES source_file(file_id),
    source_locator TEXT NOT NULL CHECK (source_locator <> ''),
    UNIQUE (from_concept_id, to_concept_id, kind)
) STRICT;

CREATE TABLE revision_relation (
    revision_relation_id INTEGER PRIMARY KEY,
    from_revision_id INTEGER NOT NULL REFERENCES concept_revision(revision_id),
    to_revision_id INTEGER NOT NULL REFERENCES concept_revision(revision_id),
    kind TEXT NOT NULL,
    source_file_id INTEGER NOT NULL REFERENCES source_file(file_id),
    source_locator TEXT NOT NULL CHECK (source_locator <> ''),
    CHECK (from_revision_id <> to_revision_id),
    UNIQUE (from_revision_id, to_revision_id, kind)
) STRICT;

CREATE TABLE document (
    document_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL REFERENCES release(release_id),
    kind TEXT NOT NULL,
    language TEXT NOT NULL CHECK (language IN ('ja', 'en', 'und')),
    title TEXT NOT NULL,
    page_count INTEGER,
    source_file_id INTEGER NOT NULL UNIQUE REFERENCES source_file(file_id),
    metadata_json TEXT NOT NULL CHECK (json_valid(metadata_json))
) STRICT;

CREATE TABLE document_text (
    document_text_id INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES document(document_id),
    sequence_number INTEGER NOT NULL CHECK (sequence_number > 0),
    locator TEXT NOT NULL,
    heading TEXT,
    text TEXT NOT NULL,
    source_locator TEXT NOT NULL CHECK (source_locator <> ''),
    UNIQUE (document_id, sequence_number)
) STRICT;

CREATE TABLE document_link (
    document_id TEXT NOT NULL REFERENCES document(document_id),
    concept_id INTEGER NOT NULL REFERENCES concept(concept_id),
    kind TEXT NOT NULL,
    source_file_id INTEGER NOT NULL REFERENCES source_file(file_id),
    source_locator TEXT NOT NULL CHECK (source_locator <> ''),
    PRIMARY KEY (document_id, concept_id, kind)
) WITHOUT ROWID, STRICT;

CREATE TABLE document_revision_link (
    document_id TEXT NOT NULL REFERENCES document(document_id),
    revision_id INTEGER NOT NULL REFERENCES concept_revision(revision_id),
    kind TEXT NOT NULL,
    source_file_id INTEGER NOT NULL REFERENCES source_file(file_id),
    source_locator TEXT NOT NULL CHECK (source_locator <> ''),
    PRIMARY KEY (document_id, revision_id, kind)
) WITHOUT ROWID, STRICT;

CREATE TABLE reference_entry (
    reference_entry_id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    language TEXT NOT NULL CHECK (language IN ('ja', 'en', 'und')),
    value TEXT NOT NULL,
    source_file_id INTEGER NOT NULL REFERENCES source_file(file_id),
    source_locator TEXT NOT NULL CHECK (source_locator <> '')
) STRICT;

CREATE TABLE build_issue (
    issue_id INTEGER PRIMARY KEY,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    source_file_id INTEGER REFERENCES source_file(file_id),
    source_locator TEXT
) STRICT;

CREATE VIRTUAL TABLE concept_text_fts USING fts5(
    text,
    revision_id UNINDEXED,
    language UNINDEXED,
    kind UNINDEXED,
    tokenize = 'trigram'
);

CREATE VIRTUAL TABLE document_text_fts USING fts5(
    text,
    document_id UNINDEXED,
    sequence_number UNINDEXED,
    tokenize = 'trigram'
);

CREATE INDEX concept_lookup_idx
    ON concept(release_id, scheme, edition, normalized_code);
CREATE INDEX concept_group_idx
    ON concept(release_id, scheme, edition, record_status, concept_type, normalized_code);
CREATE INDEX concept_revision_concept_idx
    ON concept_revision(concept_id, version_indicator);
CREATE INDEX concept_revision_validity_idx
    ON concept_revision(concept_id, valid_from, valid_to);
CREATE INDEX concept_text_revision_idx ON concept_text(revision_id, language, kind);
CREATE INDEX concept_property_revision_idx ON concept_property(revision_id, name);
CREATE INDEX relation_from_idx ON relation(from_concept_id, kind);
CREATE INDEX relation_to_idx ON relation(to_concept_id, kind);
CREATE INDEX revision_relation_from_idx ON revision_relation(from_revision_id, kind);
CREATE INDEX revision_relation_to_idx ON revision_relation(to_revision_id, kind);
CREATE INDEX document_kind_idx ON document(release_id, kind, language);
CREATE INDEX document_text_document_idx ON document_text(document_id, sequence_number);
CREATE INDEX document_text_locator_idx ON document_text(document_id, source_locator);
CREATE INDEX document_link_concept_idx ON document_link(concept_id, kind);
CREATE INDEX document_revision_link_revision_idx ON document_revision_link(revision_id, kind);
CREATE INDEX reference_entry_lookup_idx ON reference_entry(category, key, language);
CREATE INDEX build_issue_severity_idx ON build_issue(severity, code);
"""
