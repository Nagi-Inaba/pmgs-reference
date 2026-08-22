import { getDocument, lookupClassification } from "./api";
import { PublicError, unavailable } from "./errors";
import { selectPageFormat } from "./http";
import {
  cleanEdition,
  decodePathSegment,
  parseReleaseCatalog,
  pathSegment,
} from "./normalization";
import { decorateResponse } from "./responses";
import { ArtifactReader } from "./storage";

interface ObjectRoute {
  key: string;
  cache: "immutable" | "current";
  api: boolean;
  varyAccept: boolean;
  missing: "not_found" | "unavailable";
  contentType?: string;
}

interface RedirectRoute {
  location: string;
}

type ResolvedRoute = ObjectRoute | RedirectRoute;

const DOCUMENT_ID = /^doc-[a-f0-9]{24}$/u;
const CHUNK_ID = /^\d{3}$/u;
const DIRECT_FILE = /^(?:manifest|coverage|publication-policy)\.json$/u;
const GROUP_FILE = /^(?:manifest\.json|\d{3}\.json)$/u;
const ROOT_OBJECTS: Readonly<Record<string, string>> = {
  "/": "index.html",
  "/ja/": "index.html",
  "/en/": "index.en.html",
  "/openapi.json": "openapi.json",
  "/llms.txt": "llms.txt",
  "/llms.en.txt": "llms.en.txt",
  "/robots.txt": "robots.txt",
  "/sitemap.xml": "sitemap.xml",
  "/assets/style.css": "assets/style.css",
};

function splitPath(pathname: string): string[] | null {
  if (pathname === "/") {
    return [];
  }
  if (!pathname.startsWith("/") || pathname.endsWith("/") || pathname.includes("//")) {
    return null;
  }
  return pathname.slice(1).split("/");
}

function knownRelease(env: Env, release: string): boolean {
  const catalog = parseReleaseCatalog(env.RELEASE_CATALOG_JSON);
  if (catalog === null || !catalog.has(env.CURRENT_RELEASE)) {
    throw unavailable("release catalog configuration is invalid");
  }
  return catalog.has(release);
}

function decodedSegment(value: string, maxLength = 128): string | null {
  const decoded = decodePathSegment(value, maxLength);
  return decoded === null ? null : pathSegment(decoded);
}

function pageObjectRoute(pathname: string, env: Env, accept: string): ResolvedRoute | null {
  const segments = splitPath(pathname);
  if (segments === null || segments.length < 3) {
    return null;
  }
  const language = segments[0];
  if (language !== "ja" && language !== "en") {
    return null;
  }
  const kind = segments[1];
  const wantsMarkdown = selectPageFormat(accept) === "markdown";
  const suffix = wantsMarkdown ? "md" : "html";
  let objectSuffix: string;
  let chunk: string;
  if ((kind === "classification" || kind === "fterm") && segments.length <= 4) {
    const group = segments[2] === undefined ? null : decodedSegment(segments[2]);
    chunk = segments[3] ?? "001";
    if (group === null || !CHUNK_ID.test(chunk)) {
      return null;
    }
    if (segments[3] === "001") {
      return { location: `/${language}/${kind}/${segments[2]}` };
    }
    objectSuffix = `${kind}/${group}/${chunk}.${suffix}`;
  } else if (kind === "ipc" && segments.length >= 4 && segments.length <= 5) {
    const rawEdition = segments[2];
    const rawGroup = segments[3];
    if (rawEdition === undefined || rawGroup === undefined) {
      return null;
    }
    const edition = cleanEdition(decodePathSegment(rawEdition, 64));
    const group = decodedSegment(rawGroup);
    chunk = segments[4] ?? "001";
    if (edition === null || group === null || !CHUNK_ID.test(chunk)) {
      return null;
    }
    if (segments[4] === "001") {
      return { location: `/${language}/ipc/${pathSegment(edition)}/${rawGroup}` };
    }
    objectSuffix = `ipc/${pathSegment(edition)}/${group}/${chunk}.${suffix}`;
  } else if (kind === "documents" && segments.length <= 4) {
    const documentId = segments[2];
    chunk = segments[3] ?? "001";
    if (documentId === undefined || !DOCUMENT_ID.test(documentId) || !CHUNK_ID.test(chunk)) {
      return null;
    }
    if (segments[3] === "001") {
      return { location: `/${language}/documents/${documentId}` };
    }
    objectSuffix = `documents/${documentId}/${chunk}.${suffix}`;
  } else {
    return null;
  }
  return {
    key: `releases/${env.CURRENT_RELEASE}/site/${language}/${objectSuffix}`,
    cache: "current",
    api: false,
    varyAccept: true,
    missing: "not_found",
    contentType: wantsMarkdown ? "text/markdown; charset=utf-8" : "text/html; charset=utf-8",
  };
}

function directReleaseRoute(pathname: string, env: Env): ObjectRoute | null {
  const segments = splitPath(pathname);
  if (segments === null || segments[0] !== "releases" || segments.length < 3) {
    return null;
  }
  const release = segments[1];
  if (release === undefined || !knownRelease(env, release)) {
    return null;
  }
  const tail = segments.slice(2);
  let key: string | null = null;
  if (tail.length === 1 && tail[0] !== undefined && DIRECT_FILE.test(tail[0])) {
    key = `releases/${release}/${tail[0]}`;
  } else if (
    tail[0] === "groups" &&
    (tail[1] === "classification" || tail[1] === "fterm") &&
    tail.length === 4
  ) {
    const group = tail[2] === undefined ? null : decodedSegment(tail[2]);
    const file = tail[3];
    if (group !== null && file !== undefined && GROUP_FILE.test(file)) {
      key = `releases/${release}/groups/${tail[1]}/${group}/${file}`;
    }
  } else if (tail[0] === "groups" && tail[1] === "ipc" && tail.length === 5) {
    const rawEdition = tail[2];
    const rawGroup = tail[3];
    const file = tail[4];
    const edition = rawEdition === undefined ? null : cleanEdition(decodePathSegment(rawEdition, 64));
    const group = rawGroup === undefined ? null : decodedSegment(rawGroup);
    if (edition !== null && group !== null && file !== undefined && GROUP_FILE.test(file)) {
      key = `releases/${release}/groups/ipc/${pathSegment(edition)}/${group}/${file}`;
    }
  } else if (tail[0] === "documents" && tail.length === 3) {
    const documentId = tail[1];
    const file = tail[2];
    if (documentId !== undefined && DOCUMENT_ID.test(documentId) && file !== undefined && GROUP_FILE.test(file)) {
      key = `releases/${release}/documents/${documentId}/${file}`;
    }
  }
  if (key === null) {
    return null;
  }
  return {
    key,
    cache: "immutable",
    api: false,
    varyAccept: false,
    missing: "not_found",
    contentType: "application/json; charset=utf-8",
  };
}

function staticObjectRoute(pathname: string): ObjectRoute | null {
  const key = ROOT_OBJECTS[pathname];
  if (key !== undefined) {
    return {
      key,
      cache: "current",
      api: false,
      varyAccept: false,
      missing: "unavailable",
    };
  }
  if (/^\/sitemaps\/sitemap-\d{3}\.xml$/u.test(pathname)) {
    return {
      key: pathname.slice(1),
      cache: "current",
      api: false,
      varyAccept: false,
      missing: "not_found",
      contentType: "application/xml; charset=utf-8",
    };
  }
  return null;
}

function fallbackContentType(key: string): string {
  if (key.endsWith(".json")) return "application/json; charset=utf-8";
  if (key.endsWith(".html")) return "text/html; charset=utf-8";
  if (key.endsWith(".md")) return "text/markdown; charset=utf-8";
  if (key.endsWith(".xml")) return "application/xml; charset=utf-8";
  if (key.endsWith(".css")) return "text/css; charset=utf-8";
  return "text/plain; charset=utf-8";
}

async function serveR2Object(request: Request, env: Env, route: ObjectRoute): Promise<Response> {
  const reader = new ArtifactReader(env.PMGS_BUCKET, 1);
  const object = await reader.getObject(route.key);
  if (object === null) {
    if (route.missing === "unavailable") {
      throw unavailable();
    }
    throw new PublicError(404, "NOT_FOUND", "resource not found");
  }
  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("Content-Type", route.contentType ?? headers.get("Content-Type") ?? fallbackContentType(route.key));
  headers.set("Content-Length", String(object.size));
  headers.set("ETag", object.httpEtag);
  const ifNoneMatch = request.headers.get("If-None-Match");
  if (
    ifNoneMatch !== null &&
    (ifNoneMatch.trim() === "*" || ifNoneMatch.split(",").some((value) => value.trim() === object.httpEtag))
  ) {
    return decorateResponse(new Response(null, { status: 304, headers }), {
      api: route.api,
      cache: route.cache,
      varyAccept: route.varyAccept,
      r2Reads: reader.reads,
    });
  }
  return decorateResponse(new Response(object.body, { status: 200, headers }), {
    api: route.api,
    cache: route.cache,
    varyAccept: route.varyAccept,
    r2Reads: reader.reads,
  });
}

async function serveAsset(request: Request, env: Env): Promise<Response> {
  const response = await env.ASSETS.fetch(request);
  if (response.status === 404) {
    throw new PublicError(404, "NOT_FOUND", "resource not found");
  }
  return decorateResponse(response, { cache: "current" });
}

export function isApiPath(pathname: string): boolean {
  return pathname === "/api" || pathname.startsWith("/api/");
}

export async function routeRequest(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  if (url.pathname === "/assets/webmcp.js") {
    return await serveAsset(request, env);
  }
  if (url.pathname === "/api/v1/lookup") {
    return await lookupClassification(request, env);
  }
  const documentMatch = /^\/api\/v1\/documents\/(doc-[a-f0-9]{24})$/u.exec(url.pathname);
  if (documentMatch?.[1] !== undefined) {
    return await getDocument(request, env, documentMatch[1]);
  }
  if (url.pathname === "/api/v1/releases" || url.pathname === "/api/v1/coverage") {
    const route: ObjectRoute = {
      key: url.pathname === "/api/v1/releases" ? "api/v1/releases.json" : "api/v1/coverage.json",
      cache: "current",
      api: true,
      varyAccept: false,
      missing: "unavailable",
      contentType: "application/json; charset=utf-8",
    };
    return await serveR2Object(request, env, route);
  }

  const pageRoute = pageObjectRoute(url.pathname, env, request.headers.get("Accept") ?? "");
  if (pageRoute !== null) {
    if ("location" in pageRoute) {
      return decorateResponse(Response.redirect(new URL(pageRoute.location, url), 308), {
        cache: "current",
      });
    }
    return await serveR2Object(request, env, pageRoute);
  }
  const directRoute = directReleaseRoute(url.pathname, env);
  if (directRoute !== null) {
    return await serveR2Object(request, env, directRoute);
  }
  const staticRoute = staticObjectRoute(url.pathname);
  if (staticRoute !== null) {
    return await serveR2Object(request, env, staticRoute);
  }
  throw new PublicError(404, "NOT_FOUND", "resource not found");
}
