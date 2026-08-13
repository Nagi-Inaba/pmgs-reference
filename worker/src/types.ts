export type Scheme = "fi" | "fterm" | "ipc";
export type Language = "ja" | "en";

export type JsonPrimitive = boolean | number | string | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface ReleaseCatalogEntry {
  ipc_edition: string;
}

export interface GroupChunkEntry {
  chunk_id: string;
  first_lookup_key: string;
  last_lookup_key: string;
  record_count: number;
  json_key: string;
  json_bytes: number;
  json_sha256: string;
}

export interface GroupManifest {
  schema_version: string;
  release_id: string;
  group_kind: string;
  edition: string | null;
  group_key: string;
  record_count: number;
  chunks: GroupChunkEntry[];
}

export interface StorageRecord {
  schema_version: string;
  release_id: string;
  reference_date: string;
  lookup_key: string;
  scheme: Scheme;
  edition: string | null;
  code: string;
  normalized_code: string;
  record_status: "canonical" | "reference_only";
  match_status: "exact" | "not_valid_at_release";
  version: string | null;
  valid_from: string | null;
  valid_to: string | null;
  available_versions: AvailableVersion[];
  labels: SourcedText[];
  texts: SourcedText[];
  properties: SourcedProperty[];
  relations: RelationRecord[];
  documents: DocumentLink[];
  sources: PublicSource[];
  relation_count: number;
  relation_offset: number;
  relation_limit: number;
  next_relation_offset: number | null;
  revision_records: RevisionRecord[];
  fragment: string;
  canonical_urls: CanonicalUrls;
}

export interface RevisionRecord {
  version: string | null;
  valid_from: string | null;
  valid_to: string | null;
  labels: SourcedText[];
  texts: SourcedText[];
  properties: SourcedProperty[];
  relations: RelationRecord[];
  documents: DocumentLink[];
  sources: PublicSource[];
}

export interface AvailableVersion extends JsonObject {
  version: string | null;
  valid_from: string | null;
  valid_to: string | null;
}

export interface SourcedText extends JsonObject {
  kind: string;
  language: Language;
  text: string;
  provenance: "official";
  source_id: string;
  locator: string;
}

export interface SourcedProperty extends JsonObject {
  name: string;
  value: string;
  language: Language | null;
  provenance: "official";
  source_id: string;
  locator: string;
}

export interface RelationRecord extends JsonObject {
  type: string;
  scheme: Scheme;
  code: string;
  edition: string | null;
  version: string | null;
  source_id: string;
  locator: string;
}

export interface DocumentLink extends JsonObject {
  document_id: string;
  kind: string;
  language: Language | "und";
  title: string;
  page_count: number | null;
  link_type: string;
  source_id: string;
  locator: string;
}

export interface CanonicalUrls extends JsonObject {
  ja: string;
  en?: string;
}

export interface PublicSource extends JsonObject {
  source_id: string;
  title: string;
  relative_id: string;
  owner: string;
  original_url: string;
  sha256: string;
  attribution: string;
}

export interface ClassificationChunk {
  schema_version: string;
  release_id: string;
  chunk_id: string;
  records: StorageRecord[];
}

export interface DocumentChunkEntry {
  chunk_id: string;
  first_sequence: number | null;
  last_sequence: number | null;
  pages: number[];
  segment_count: number;
  json_key: string;
  json_bytes: number;
  json_sha256: string;
  url: string;
}

export interface DocumentManifest {
  schema_version: string;
  release_id: string;
  document_id: string;
  kind: string;
  language: string;
  site_language: Language;
  title: string;
  page_count: number | null;
  metadata: JsonValue;
  segment_count: number;
  source: PublicSource;
  chunks: DocumentChunkEntry[];
}

export interface DocumentSegment extends JsonObject {
  sequence_number: number;
  locator: string;
  heading: string | null;
  text: string;
  source_locator: string;
  related_classifications: JsonObject[];
}

export interface DocumentChunk {
  schema_version: string;
  release_id: string;
  document_id: string;
  chunk_id: string;
  segments: DocumentSegment[];
}

export function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNonEmptyString(value: unknown): value is string {
  return isString(value) && value.length > 0;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || isString(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && typeof value === "number" && value >= 0;
}

function isNullableNonNegativeInteger(value: unknown): value is number | null {
  return value === null || isNonNegativeInteger(value);
}

function isJsonObjectArray(value: unknown): value is JsonObject[] {
  return Array.isArray(value) && value.every(isJsonObject);
}

function isLanguage(value: unknown): value is Language {
  return value === "ja" || value === "en";
}

function isAvailableVersion(value: unknown): value is AvailableVersion {
  return (
    isJsonObject(value) &&
    isNullableString(value.version) &&
    isNullableString(value.valid_from) &&
    isNullableString(value.valid_to)
  );
}

function isSourcedText(value: unknown): value is SourcedText {
  return (
    isJsonObject(value) &&
    isNonEmptyString(value.kind) &&
    isLanguage(value.language) &&
    isString(value.text) &&
    value.provenance === "official" &&
    isNonEmptyString(value.source_id) &&
    isNonEmptyString(value.locator)
  );
}

function isSourcedProperty(value: unknown): value is SourcedProperty {
  return (
    isJsonObject(value) &&
    isNonEmptyString(value.name) &&
    isString(value.value) &&
    (value.language === null || isLanguage(value.language)) &&
    value.provenance === "official" &&
    isNonEmptyString(value.source_id) &&
    isNonEmptyString(value.locator)
  );
}

function isRelationRecord(value: unknown): value is RelationRecord {
  return (
    isJsonObject(value) &&
    isNonEmptyString(value.type) &&
    isScheme(value.scheme) &&
    isNonEmptyString(value.code) &&
    isNullableString(value.edition) &&
    isNullableString(value.version) &&
    isNonEmptyString(value.source_id) &&
    isNonEmptyString(value.locator)
  );
}

function isDocumentLink(value: unknown): value is DocumentLink {
  return (
    isJsonObject(value) &&
    isNonEmptyString(value.document_id) &&
    isNonEmptyString(value.kind) &&
    (isLanguage(value.language) || value.language === "und") &&
    isNonEmptyString(value.title) &&
    isNullableNonNegativeInteger(value.page_count) &&
    isNonEmptyString(value.link_type) &&
    isNonEmptyString(value.source_id) &&
    isNonEmptyString(value.locator)
  );
}

function isCanonicalUrls(value: unknown): value is CanonicalUrls {
  return (
    isJsonObject(value) &&
    isNonEmptyString(value.ja) &&
    (value.en === undefined || isNonEmptyString(value.en))
  );
}

function isRevisionRecord(value: unknown): value is RevisionRecord {
  return (
    isJsonObject(value) &&
    isNullableString(value.version) &&
    isNullableString(value.valid_from) &&
    isNullableString(value.valid_to) &&
    Array.isArray(value.labels) &&
    value.labels.every(isSourcedText) &&
    Array.isArray(value.texts) &&
    value.texts.every(isSourcedText) &&
    Array.isArray(value.properties) &&
    value.properties.every(isSourcedProperty) &&
    Array.isArray(value.relations) &&
    value.relations.every(isRelationRecord) &&
    Array.isArray(value.documents) &&
    value.documents.every(isDocumentLink) &&
    Array.isArray(value.sources) &&
    value.sources.every(isPublicSource)
  );
}

function isPublicSource(value: unknown): value is PublicSource {
  return (
    isJsonObject(value) &&
    isNonEmptyString(value.source_id) &&
    isNonEmptyString(value.title) &&
    isNonEmptyString(value.relative_id) &&
    isNonEmptyString(value.owner) &&
    isNonEmptyString(value.original_url) &&
    isString(value.sha256) &&
    /^[A-F0-9]{64}$/.test(value.sha256) &&
    isNonEmptyString(value.attribution)
  );
}

function isScheme(value: unknown): value is Scheme {
  return value === "fi" || value === "fterm" || value === "ipc";
}

export function isGroupManifest(value: unknown): value is GroupManifest {
  if (!isJsonObject(value) || !Array.isArray(value.chunks)) {
    return false;
  }
  return (
    value.schema_version === "2.0" &&
    isString(value.release_id) &&
    isString(value.group_kind) &&
    isNullableString(value.edition) &&
    isString(value.group_key) &&
    isNonNegativeInteger(value.record_count) &&
    value.chunks.every(
      (entry) =>
        isJsonObject(entry) &&
        isString(entry.chunk_id) &&
        /^\d{3}$/.test(entry.chunk_id) &&
        isString(entry.first_lookup_key) &&
        isString(entry.last_lookup_key) &&
        isNonNegativeInteger(entry.record_count) &&
        isString(entry.json_key) &&
        isNonNegativeInteger(entry.json_bytes) &&
        isString(entry.json_sha256),
    )
  );
}

export function isStorageRecord(value: unknown): value is StorageRecord {
  return (
    isJsonObject(value) &&
    value.schema_version === "2.0" &&
    isNonEmptyString(value.release_id) &&
    isNonEmptyString(value.reference_date) &&
    isNonEmptyString(value.lookup_key) &&
    isScheme(value.scheme) &&
    isNullableString(value.edition) &&
    isNonEmptyString(value.code) &&
    isNonEmptyString(value.normalized_code) &&
    (value.record_status === "canonical" || value.record_status === "reference_only") &&
    (value.match_status === "exact" || value.match_status === "not_valid_at_release") &&
    isNullableString(value.version) &&
    isNullableString(value.valid_from) &&
    isNullableString(value.valid_to) &&
    Array.isArray(value.available_versions) &&
    value.available_versions.every(isAvailableVersion) &&
    Array.isArray(value.labels) &&
    value.labels.every(isSourcedText) &&
    Array.isArray(value.texts) &&
    value.texts.every(isSourcedText) &&
    Array.isArray(value.properties) &&
    value.properties.every(isSourcedProperty) &&
    Array.isArray(value.relations) &&
    value.relations.every(isRelationRecord) &&
    Array.isArray(value.documents) &&
    value.documents.every(isDocumentLink) &&
    Array.isArray(value.sources) &&
    value.sources.every(isPublicSource) &&
    isNonNegativeInteger(value.relation_count) &&
    isNonNegativeInteger(value.relation_offset) &&
    isNonNegativeInteger(value.relation_limit) &&
    value.relation_limit >= 1 &&
    value.relation_limit <= 200 &&
    isNullableNonNegativeInteger(value.next_relation_offset) &&
    Array.isArray(value.revision_records) &&
    value.revision_records.every(isRevisionRecord) &&
    isNonEmptyString(value.fragment) &&
    isCanonicalUrls(value.canonical_urls)
  );
}

export function isClassificationChunk(value: unknown): value is ClassificationChunk {
  return (
    isJsonObject(value) &&
    value.schema_version === "2.0" &&
    isString(value.release_id) &&
    isString(value.chunk_id) &&
    Array.isArray(value.records) &&
    value.records.every(isStorageRecord)
  );
}

function isDocumentChunkEntry(value: unknown): value is DocumentChunkEntry {
  return (
    isJsonObject(value) &&
    isString(value.chunk_id) &&
    /^\d{3}$/.test(value.chunk_id) &&
    isNullableNonNegativeInteger(value.first_sequence) &&
    isNullableNonNegativeInteger(value.last_sequence) &&
    Array.isArray(value.pages) &&
    value.pages.every(isNonNegativeInteger) &&
    isNonNegativeInteger(value.segment_count) &&
    isString(value.json_key) &&
    isNonNegativeInteger(value.json_bytes) &&
    isString(value.json_sha256) &&
    isString(value.url)
  );
}

export function isDocumentManifest(value: unknown): value is DocumentManifest {
  return (
    isJsonObject(value) &&
    isString(value.schema_version) &&
    isString(value.release_id) &&
    isString(value.document_id) &&
    isString(value.kind) &&
    isString(value.language) &&
    (value.site_language === "ja" || value.site_language === "en") &&
    isString(value.title) &&
    isNullableNonNegativeInteger(value.page_count) &&
    isNonNegativeInteger(value.segment_count) &&
    isPublicSource(value.source) &&
    Array.isArray(value.chunks) &&
    value.chunks.every(isDocumentChunkEntry)
  );
}

function isDocumentSegment(value: unknown): value is DocumentSegment {
  return (
    isJsonObject(value) &&
    isNonNegativeInteger(value.sequence_number) &&
    isString(value.locator) &&
    isNullableString(value.heading) &&
    isString(value.text) &&
    isString(value.source_locator) &&
    isJsonObjectArray(value.related_classifications)
  );
}

export function isDocumentChunk(value: unknown): value is DocumentChunk {
  return (
    isJsonObject(value) &&
    isString(value.schema_version) &&
    isString(value.release_id) &&
    isString(value.document_id) &&
    isString(value.chunk_id) &&
    Array.isArray(value.segments) &&
    value.segments.every(isDocumentSegment)
  );
}
