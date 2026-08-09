import type { ReleaseCatalogEntry, Scheme } from "./types";

const SAFE_RELEASE = /^[A-Za-z0-9._-]{1,64}$/u;
const SAFE_EDITION = /^[A-Za-z0-9._-]{1,64}$/u;

function hasControlCharacter(value: string): boolean {
  return [...value].some((character) => {
    const codePoint = character.codePointAt(0);
    return codePoint !== undefined && (codePoint <= 31 || codePoint === 127);
  });
}

export function normalizeCode(scheme: Scheme, code: string): string {
  void scheme;
  return code.replace(/\s+/gu, "").toUpperCase();
}

export function groupKey(scheme: Scheme, normalizedCode: string): string {
  if (scheme === "fterm") {
    return normalizedCode.slice(0, 5);
  }
  const slash = normalizedCode.indexOf("/");
  return slash >= 0 ? normalizedCode.slice(0, slash) : normalizedCode;
}

export function lookupKey(scheme: Scheme, edition: string | null, normalizedCode: string): string {
  return `${scheme}\u001f${edition ?? ""}\u001f${normalizedCode}`;
}

export function pathSegment(value: string): string {
  return encodeURIComponent(value).replace(/[!'()*]/gu, (character) =>
    `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

export function cleanCode(value: string | null): { clean: string; normalizedInput: string } | null {
  if (value === null) {
    return null;
  }
  const clean = value.trim();
  if (clean.length === 0 || clean.length > 128 || hasControlCharacter(clean)) {
    return null;
  }
  return { clean, normalizedInput: clean.replace(/\s+/gu, "").toUpperCase() };
}

export function cleanEdition(value: string | null): string | null {
  if (value === null) {
    return null;
  }
  const clean = value.trim().toUpperCase();
  return SAFE_EDITION.test(clean) ? clean : null;
}

export function cleanRelease(value: string): string | null {
  return SAFE_RELEASE.test(value) ? value : null;
}

export function decodePathSegment(value: string, maxLength = 128): string | null {
  try {
    const decoded = decodeURIComponent(value);
    if (
      decoded.length === 0 ||
      decoded.length > maxLength ||
      decoded.includes("/") ||
      decoded.includes("\\") ||
      hasControlCharacter(decoded)
    ) {
      return null;
    }
    return decoded;
  } catch {
    return null;
  }
}

export function parseReleaseCatalog(value: string): Map<string, ReleaseCatalogEntry> | null {
  let raw: unknown;
  try {
    raw = JSON.parse(value);
  } catch {
    return null;
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return null;
  }
  const catalog = new Map<string, ReleaseCatalogEntry>();
  for (const [release, entry] of Object.entries(raw)) {
    if (
      cleanRelease(release) === null ||
      typeof entry !== "object" ||
      entry === null ||
      Array.isArray(entry) ||
      !("ipc_edition" in entry) ||
      typeof entry.ipc_edition !== "string"
    ) {
      return null;
    }
    const ipcEdition = cleanEdition(entry.ipc_edition);
    if (ipcEdition === null) {
      return null;
    }
    catalog.set(release, { ipc_edition: ipcEdition });
  }
  return catalog.size > 0 ? catalog : null;
}
