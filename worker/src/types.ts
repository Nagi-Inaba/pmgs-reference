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
  lookup_key: string;
  scheme: Scheme;
  edition: string | null;
  code: string;
  normalized_code: string;
  labels: JsonObject[];
  texts: JsonObject[];
  properties: JsonObject[];
  relations: JsonObject[];
  documents: JsonObject[];
  sources: PublicSource[];
  fragment: string;
  canonical_urls: JsonObject;
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

function isPublicSource(value: unknown): value is PublicSource {
  return (
    isJsonObject(value) &&
    isString(value.source_id) &&
    isString(value.title) &&
    isString(value.relative_id) &&
    isString(value.owner) &&
    isString(value.original_url) &&
    isString(value.sha256) &&
    isString(value.attribution)
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
    isString(value.schema_version) &&
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
    isString(value.schema_version) &&
    isString(value.release_id) &&
    isString(value.lookup_key) &&
    isScheme(value.scheme) &&
    isNullableString(value.edition) &&
    isString(value.code) &&
    isString(value.normalized_code) &&
    isJsonObjectArray(value.labels) &&
    isJsonObjectArray(value.texts) &&
    isJsonObjectArray(value.properties) &&
    isJsonObjectArray(value.relations) &&
    isJsonObjectArray(value.documents) &&
    Array.isArray(value.sources) &&
    value.sources.every(isPublicSource) &&
    isString(value.fragment) &&
    isJsonObject(value.canonical_urls)
  );
}

export function isClassificationChunk(value: unknown): value is ClassificationChunk {
  return (
    isJsonObject(value) &&
    isString(value.schema_version) &&
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
