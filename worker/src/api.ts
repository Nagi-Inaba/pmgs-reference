import { PublicError, unavailable } from "./errors";
import {
  cleanCode,
  cleanEdition,
  groupKey,
  lookupKey,
  normalizeCode,
  parseReleaseCatalog,
  pathSegment,
} from "./normalization";
import { jsonResponse } from "./responses";
import { ArtifactReader } from "./storage";
import {
  type DocumentChunkEntry,
  type GroupChunkEntry,
  type JsonObject,
  type Language,
  type ReleaseCatalogEntry,
  type Scheme,
  type StorageRecord,
  type RevisionRecord,
  isClassificationChunk,
  isDocumentChunk,
  isDocumentManifest,
  isGroupManifest,
} from "./types";

const ALLOWED_LOOKUP_PARAMETERS = new Set([
  "scheme",
  "code",
  "release",
  "edition",
  "language",
  "version",
  "relation_limit",
  "relation_offset",
]);
const ALLOWED_DOCUMENT_PARAMETERS = new Set(["release", "page", "section"]);
const DOCUMENT_ID = /^doc-[a-f0-9]{24}$/u;

interface ResolvedRelease {
  id: string;
  entry: ReleaseCatalogEntry;
  currentAlias: boolean;
}

function singleParameter(
  parameters: URLSearchParams,
  name: string,
  required = false,
): string | null {
  const values = parameters.getAll(name);
  if (values.length > 1) {
    throw new PublicError(400, "INVALID_QUERY", `query parameter must occur once: ${name}`);
  }
  const value = values[0] ?? null;
  if (required && (value === null || value.trim() === "")) {
    throw new PublicError(400, "INVALID_QUERY", `missing query parameter: ${name}`);
  }
  return value;
}

function rejectUnknownParameters(parameters: URLSearchParams, allowed: Set<string>): void {
  for (const name of parameters.keys()) {
    if (!allowed.has(name)) {
      throw new PublicError(400, "INVALID_QUERY", `unsupported query parameter: ${name}`);
    }
  }
}

function schemeParameter(value: string | null): Scheme {
  const normalized = value?.trim().toLowerCase();
  if (normalized !== "fi" && normalized !== "fterm" && normalized !== "ipc") {
    throw new PublicError(400, "INVALID_SCHEME", "scheme must be fi, fterm, or ipc");
  }
  return normalized;
}

function languageParameter(value: string | null): Language {
  const normalized = (value ?? "ja").trim().toLowerCase();
  if (normalized !== "ja" && normalized !== "en") {
    throw new PublicError(400, "INVALID_LANGUAGE", "language must be ja or en");
  }
  return normalized;
}

function releaseCatalog(env: Env): Map<string, ReleaseCatalogEntry> {
  const catalog = parseReleaseCatalog(env.RELEASE_CATALOG_JSON);
  if (catalog === null || !catalog.has(env.CURRENT_RELEASE)) {
    throw unavailable("release catalog configuration is invalid");
  }
  return catalog;
}

function resolveRelease(value: string | null, env: Env): ResolvedRelease {
  const catalog = releaseCatalog(env);
  const requested = value?.trim() || "current";
  const currentAlias = requested === "current";
  const releaseId = currentAlias ? env.CURRENT_RELEASE : requested;
  const entry = catalog.get(releaseId);
  if (entry === undefined) {
    throw new PublicError(404, "RELEASE_NOT_FOUND", "published release not found");
  }
  return { id: releaseId, entry, currentAlias };
}

function integerParameter(value: string | null, name: string): number | null {
  if (value === null) {
    return null;
  }
  if (!/^[1-9][0-9]*$/u.test(value)) {
    throw new PublicError(400, "INVALID_QUERY", `${name} must be a positive integer`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) {
    throw new PublicError(400, "INVALID_QUERY", `${name} is too large`);
  }
  return parsed;
}

function relationPageParameter(
  value: string | null,
  name: "relation_limit" | "relation_offset",
  fallback: number,
): number {
  if (value === null) return fallback;
  if (!/^[0-9]+$/u.test(value)) {
    throw new PublicError(400, "INVALID_QUERY", `${name} must be a non-negative integer`);
  }
  const parsed = Number(value);
  const valid = Number.isSafeInteger(parsed) && (name === "relation_offset" || parsed >= 1);
  if (!valid || (name === "relation_limit" && parsed > 200)) {
    throw new PublicError(400, "INVALID_QUERY", `${name} is outside the supported range`);
  }
  return parsed;
}

function versionParameter(value: string | null, scheme: Scheme): string | null {
  if (value === null) return null;
  if (scheme !== "ipc") {
    throw new PublicError(400, "INVALID_VERSION", "version is supported only for IPC");
  }
  let normalized = value.trim();
  if (normalized.startsWith("(") && normalized.endsWith(")")) {
    normalized = normalized.slice(1, -1).trim();
  }
  if (!/^[0-9]{4}\.[0-9]{2}$/u.test(normalized)) {
    throw new PublicError(400, "INVALID_VERSION", "IPC version must use YYYY.MM");
  }
  return normalized;
}

function findGroupChunk(chunks: GroupChunkEntry[], target: string): GroupChunkEntry | null {
  let lower = 0;
  let upper = chunks.length - 1;
  while (lower <= upper) {
    const middle = Math.floor((lower + upper) / 2);
    const candidate = chunks[middle];
    if (candidate === undefined) {
      return null;
    }
    if (target < candidate.first_lookup_key) {
      upper = middle - 1;
    } else if (target > candidate.last_lookup_key) {
      lower = middle + 1;
    } else {
      return candidate;
    }
  }
  return null;
}

function languageItems(items: JsonObject[], language: Language, includeNeutral = false): JsonObject[] {
  return items.filter((item) => {
    const itemLanguage = item.language;
    return itemLanguage === language || (includeNeutral && itemLanguage === null);
  });
}

function projectRecord(
  record: StorageRecord,
  language: Language,
  matchStatus: "exact" | "normalized_exact",
  version: string | null,
  relationLimit: number,
  relationOffset: number,
): JsonObject {
  const canonical = record.canonical_urls[language] ?? record.canonical_urls.ja;
  if (typeof canonical !== "string") {
    throw unavailable("classification record has no canonical URL");
  }
  let selected: RevisionRecord | null = null;
  let selectedStatus: string = record.match_status;
  if (version !== null) {
    selected = record.revision_records.find((candidate) => candidate.version === version) ?? null;
    selectedStatus = selected === null ? "version_not_found" : matchStatus;
  } else if (record.match_status === "exact") {
    selected =
      record.revision_records.find((candidate) => candidate.version === record.version) ?? null;
    if (selected === null) {
      throw unavailable("classification record is missing its selected revision");
    }
    selectedStatus = matchStatus;
  }
  const allRelations = selected?.relations ?? [];
  const relations = allRelations.slice(relationOffset, relationOffset + relationLimit);
  const nextOffset = relationOffset + relations.length;
  return {
    schema_version: record.schema_version,
    release_id: record.release_id,
    reference_date: record.reference_date,
    scheme: record.scheme,
    edition: record.edition,
    code: record.code,
    normalized_code: record.normalized_code,
    record_status: record.record_status,
    match_status: selectedStatus,
    version: selected?.version ?? null,
    valid_from: selected?.valid_from ?? null,
    valid_to: selected?.valid_to ?? null,
    available_versions: record.available_versions,
    labels: languageItems(selected?.labels ?? [], language),
    texts: languageItems(selected?.texts ?? [], language),
    properties: languageItems(selected?.properties ?? [], language, true),
    relation_count: allRelations.length,
    relation_offset: relationOffset,
    relation_limit: relationLimit,
    relations_truncated: allRelations.length > relations.length,
    next_relation_offset: nextOffset < allRelations.length ? nextOffset : null,
    relations,
    documents: selected?.documents ?? [],
    sources: selected?.sources ?? record.sources,
    canonical_url: canonical,
  };
}

function groupObjectPrefix(
  releaseId: string,
  scheme: Scheme,
  edition: string | null,
  grouping: string,
  latestIpcEdition: string,
): string {
  const encodedGroup = pathSegment(grouping);
  if (scheme === "fterm") {
    return `releases/${releaseId}/groups/fterm/${encodedGroup}`;
  }
  if (scheme === "ipc" && edition !== latestIpcEdition) {
    return `releases/${releaseId}/groups/ipc/${pathSegment(edition ?? "")}/${encodedGroup}`;
  }
  return `releases/${releaseId}/groups/classification/${encodedGroup}`;
}

export async function lookupClassification(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  rejectUnknownParameters(url.searchParams, ALLOWED_LOOKUP_PARAMETERS);
  const scheme = schemeParameter(singleParameter(url.searchParams, "scheme", true));
  const rawCode = singleParameter(url.searchParams, "code");
  const checkedCode = cleanCode(rawCode);
  if (checkedCode === null) {
    throw new PublicError(400, "INVALID_CODE", "code must be 1 to 128 printable characters");
  }
  const normalizedCode = normalizeCode(scheme, checkedCode.clean);
  if (normalizedCode.length === 0) {
    throw new PublicError(400, "INVALID_CODE", "code must contain a classification value");
  }
  const language = languageParameter(singleParameter(url.searchParams, "language"));
  const release = resolveRelease(singleParameter(url.searchParams, "release"), env);
  const version = versionParameter(singleParameter(url.searchParams, "version"), scheme);
  const relationLimit = relationPageParameter(
    singleParameter(url.searchParams, "relation_limit"),
    "relation_limit",
    50,
  );
  const relationOffset = relationPageParameter(
    singleParameter(url.searchParams, "relation_offset"),
    "relation_offset",
    0,
  );
  const rawEdition = singleParameter(url.searchParams, "edition");
  if (scheme !== "ipc" && rawEdition !== null) {
    throw new PublicError(400, "INVALID_EDITION", "edition is supported only for IPC");
  }
  const edition =
    scheme === "ipc"
      ? rawEdition === null
        ? release.entry.ipc_edition
        : cleanEdition(rawEdition)
      : null;
  if (scheme === "ipc" && edition === null) {
    throw new PublicError(400, "INVALID_EDITION", "edition is invalid");
  }

  const targetLookupKey = lookupKey(scheme, edition, normalizedCode);
  const grouping = groupKey(scheme, normalizedCode);
  if (grouping.length === 0) {
    throw new PublicError(400, "INVALID_CODE", "code does not produce a valid group");
  }
  const prefix = groupObjectPrefix(
    release.id,
    scheme,
    edition,
    grouping,
    release.entry.ipc_edition,
  );
  const reader = new ArtifactReader(env.PMGS_BUCKET, 2);
  const manifestPayload = await reader.getJson(`${prefix}/manifest.json`);
  if (manifestPayload === null) {
    throw new PublicError(404, "CLASSIFICATION_NOT_FOUND", "classification not found");
  }
  if (!isGroupManifest(manifestPayload) || manifestPayload.release_id !== release.id) {
    throw unavailable("group manifest is malformed");
  }
  const chunkEntry = findGroupChunk(manifestPayload.chunks, targetLookupKey);
  if (chunkEntry === null) {
    throw new PublicError(404, "CLASSIFICATION_NOT_FOUND", "classification not found");
  }
  if (!chunkEntry.json_key.startsWith(`${prefix}/`)) {
    throw unavailable("group manifest references an invalid object key");
  }
  const chunkPayload = await reader.getJson(chunkEntry.json_key);
  if (
    !isClassificationChunk(chunkPayload) ||
    chunkPayload.release_id !== release.id ||
    chunkPayload.chunk_id !== chunkEntry.chunk_id
  ) {
    throw unavailable("classification chunk is malformed");
  }
  const record = chunkPayload.records.find(
    (candidate) =>
      candidate.scheme === scheme &&
      (candidate.edition ?? "") === (edition ?? "") &&
      candidate.normalized_code === normalizedCode,
  );
  if (record === undefined) {
    throw unavailable("classification range does not contain its indexed record");
  }
  const matchStatus = checkedCode.clean === normalizedCode ? "exact" : "normalized_exact";
  return jsonResponse(
    projectRecord(record, language, matchStatus, version, relationLimit, relationOffset),
    200,
    {
    api: true,
    cache: release.currentAlias ? "current" : "immutable",
    r2Reads: reader.reads,
    },
  );
}

function findDocumentChunk(
  chunks: DocumentChunkEntry[],
  page: number | null,
  section: number | null,
): DocumentChunkEntry | null {
  if (page !== null) {
    return chunks.find((entry) => entry.pages.includes(page)) ?? null;
  }
  if (section !== null) {
    return (
      chunks.find(
        (entry) =>
          entry.first_sequence !== null &&
          entry.last_sequence !== null &&
          entry.first_sequence <= section &&
          section <= entry.last_sequence,
      ) ?? null
    );
  }
  return chunks[0] ?? null;
}

export async function getDocument(
  request: Request,
  env: Env,
  documentId: string,
): Promise<Response> {
  if (!DOCUMENT_ID.test(documentId)) {
    throw new PublicError(404, "DOCUMENT_NOT_FOUND", "document not found");
  }
  const url = new URL(request.url);
  rejectUnknownParameters(url.searchParams, ALLOWED_DOCUMENT_PARAMETERS);
  const release = resolveRelease(singleParameter(url.searchParams, "release"), env);
  const page = integerParameter(singleParameter(url.searchParams, "page"), "page");
  const section = integerParameter(singleParameter(url.searchParams, "section"), "section");
  if (page !== null && section !== null) {
    throw new PublicError(400, "INVALID_QUERY", "page and section cannot be combined");
  }

  const prefix = `releases/${release.id}/documents/${documentId}`;
  const reader = new ArtifactReader(env.PMGS_BUCKET, 2);
  const manifestPayload = await reader.getJson(`${prefix}/manifest.json`);
  if (manifestPayload === null) {
    throw new PublicError(404, "DOCUMENT_NOT_FOUND", "document not found");
  }
  if (
    !isDocumentManifest(manifestPayload) ||
    manifestPayload.release_id !== release.id ||
    manifestPayload.document_id !== documentId
  ) {
    throw unavailable();
  }
  const chunkEntry = findDocumentChunk(manifestPayload.chunks, page, section);
  if (chunkEntry === null || !chunkEntry.json_key.startsWith(`${prefix}/`)) {
    throw new PublicError(404, "DOCUMENT_SELECTOR_NOT_FOUND", "document selector not found");
  }
  const chunkPayload = await reader.getJson(chunkEntry.json_key);
  if (
    !isDocumentChunk(chunkPayload) ||
    chunkPayload.release_id !== release.id ||
    chunkPayload.document_id !== documentId ||
    chunkPayload.chunk_id !== chunkEntry.chunk_id
  ) {
    throw unavailable();
  }
  const segments = chunkPayload.segments.filter((segment) => {
    if (page !== null) {
      return segment.locator === `page:${page}` || segment.source_locator === `page:${page}`;
    }
    if (section !== null) {
      return segment.sequence_number === section;
    }
    return true;
  });
  if ((page !== null || section !== null) && segments.length === 0) {
    throw new PublicError(404, "DOCUMENT_SELECTOR_NOT_FOUND", "document selector not found");
  }
  const chunkIndex = manifestPayload.chunks.findIndex(
    (entry) => entry.chunk_id === chunkEntry.chunk_id,
  );
  const previous = chunkIndex > 0 ? manifestPayload.chunks[chunkIndex - 1]?.chunk_id ?? null : null;
  const next =
    chunkIndex >= 0 && chunkIndex + 1 < manifestPayload.chunks.length
      ? manifestPayload.chunks[chunkIndex + 1]?.chunk_id ?? null
      : null;
  return jsonResponse(
    {
      schema_version: manifestPayload.schema_version,
      release_id: manifestPayload.release_id,
      document_id: manifestPayload.document_id,
      kind: manifestPayload.kind,
      language: manifestPayload.language,
      title: manifestPayload.title,
      page_count: manifestPayload.page_count,
      metadata: manifestPayload.metadata,
      segment_count: manifestPayload.segment_count,
      segments,
      segments_truncated: segments.length < manifestPayload.segment_count,
      source: manifestPayload.source,
      chunk: { id: chunkEntry.chunk_id, previous, next },
    },
    200,
    {
      api: true,
      cache: release.currentAlias ? "current" : "immutable",
      r2Reads: reader.reads,
    },
  );
}
