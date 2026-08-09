import { PublicError } from "./errors";

const CONTENT_SIGNAL = "search=yes, ai-input=yes, ai-train=no";
const CSP = [
  "default-src 'none'",
  "base-uri 'none'",
  "connect-src 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "img-src 'self' data:",
  "object-src 'none'",
  "script-src 'self'",
  "style-src 'self'",
].join("; ");

export interface ResponseOptions {
  api?: boolean;
  cache?: "immutable" | "current" | "none";
  varyAccept?: boolean;
  r2Reads?: number;
}

function securityHeaders(headers: Headers): void {
  headers.set("Content-Security-Policy", CSP);
  headers.set("Content-Signal", CONTENT_SIGNAL);
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("X-Frame-Options", "DENY");
}

function applyOptions(headers: Headers, options: ResponseOptions): void {
  securityHeaders(headers);
  if (options.api === true) {
    headers.set("Access-Control-Allow-Origin", "*");
    headers.set("Access-Control-Expose-Headers", "Content-Signal, ETag, Server-Timing");
  }
  if (options.cache === "immutable") {
    headers.set("Cache-Control", "public, max-age=31536000, immutable");
  } else if (options.cache === "current") {
    headers.set("Cache-Control", "public, max-age=300, stale-while-revalidate=60");
  } else {
    headers.set("Cache-Control", "no-store");
  }
  if (options.varyAccept === true) {
    headers.append("Vary", "Accept");
  }
  if (options.r2Reads !== undefined) {
    headers.set("Server-Timing", `pmgs-r2;desc="${options.r2Reads} reads"`);
  }
}

export function decorateResponse(response: Response, options: ResponseOptions): Response {
  const headers = new Headers(response.headers);
  applyOptions(headers, options);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export function jsonResponse(
  payload: unknown,
  status: number,
  options: ResponseOptions,
): Response {
  const headers = new Headers({ "Content-Type": "application/json; charset=utf-8" });
  applyOptions(headers, options);
  return Response.json(payload, { status, headers });
}

export function errorResponse(error: PublicError, r2Reads = 0): Response {
  return jsonResponse(
    { error: { code: error.code, message: error.message } },
    error.status,
    { api: true, cache: "none", r2Reads },
  );
}

export function methodNotAllowed(api: boolean): Response {
  const headers = new Headers({
    Allow: "GET, HEAD, OPTIONS",
    "Content-Type": api ? "application/json; charset=utf-8" : "text/plain; charset=utf-8",
  });
  applyOptions(headers, { api, cache: "none" });
  return new Response(
    api
      ? JSON.stringify({ error: { code: "METHOD_NOT_ALLOWED", message: "method not allowed" } })
      : "Method Not Allowed\n",
    { status: 405, headers },
  );
}

export function optionsResponse(): Response {
  const headers = new Headers({
    "Access-Control-Allow-Headers": "Accept, Content-Type",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Max-Age": "86400",
  });
  applyOptions(headers, { api: true, cache: "current" });
  return new Response(null, { status: 204, headers });
}

export function textErrorResponse(error: PublicError): Response {
  const headers = new Headers({ "Content-Type": "text/plain; charset=utf-8" });
  applyOptions(headers, { cache: "none" });
  return new Response(`${error.message}\n`, { status: error.status, headers });
}
