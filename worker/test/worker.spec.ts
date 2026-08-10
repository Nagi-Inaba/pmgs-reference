import { env, exports } from "cloudflare:workers";
import { beforeAll, describe, expect, it } from "vitest";

import vectors from "../../schemas/normalization-vectors.json";
import { groupKey, normalizeCode } from "../src/normalization";
import type { Scheme } from "../src/types";
import { seedFixture, seedLargeLookupFixture } from "./fixtures";

const ORIGIN = "https://pmgs.example.test";

async function request(path: string, init?: RequestInit): Promise<Response> {
  return await exports.default.fetch(new Request(`${ORIGIN}${path}`, init));
}

async function json(response: Response): Promise<Record<string, unknown>> {
  const payload: unknown = await response.json();
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    throw new Error("expected JSON object");
  }
  return payload as Record<string, unknown>;
}

beforeAll(async () => {
  await seedFixture();
});

describe("shared normalization contract", () => {
  it("matches every Python-owned normalization vector", () => {
    for (const vector of vectors.vectors) {
      const scheme = vector.scheme as Scheme;
      const normalized = normalizeCode(scheme, vector.input);
      expect(normalized).toBe(vector.normalized);
      expect(groupKey(scheme, normalized)).toBe(vector.group_key);
    }
  });
});

describe("classification API", () => {
  it("returns a language-projected FI record with exactly two R2 reads", async () => {
    const response = await request(
      "/api/v1/lookup?scheme=fi&code=%20g06f%203%2F048%20&language=ja",
    );
    const payload = await json(response);

    expect(response.status).toBe(200);
    expect(response.headers.get("Access-Control-Allow-Origin")).toBe("*");
    expect(response.headers.get("Server-Timing")).toBe('pmgs-r2;desc="2 reads"');
    expect(response.headers.get("Content-Signal")).toBe(
      "search=yes, ai-input=yes, ai-train=no",
    );
    expect(response.headers.get("Cache-Control")).toContain("max-age=300");
    expect(payload.scheme).toBe("fi");
    expect(payload.normalized_code).toBe("G06F3/048");
    expect(payload.match_status).toBe("normalized_exact");
    expect(JSON.stringify(payload)).toContain("FI interaction 公式定義");
    expect(JSON.stringify(payload)).not.toContain("official definition");
  });

  it("distinguishes current and historical IPC editions from FI", async () => {
    const current = await json(
      await request("/api/v1/lookup?scheme=ipc&code=G06F3%2F048&language=en"),
    );
    const historical = await json(
      await request("/api/v1/lookup?scheme=ipc&code=G06F3%2F048&edition=7e"),
    );
    const fterm = await json(
      await request("/api/v1/lookup?scheme=fterm&code=4C083%20AA01"),
    );

    expect(current.edition).toBe("8U");
    expect(JSON.stringify(current)).toContain("IPC current interaction official definition");
    expect(historical.edition).toBe("7E");
    expect(JSON.stringify(historical)).toContain("IPC legacy interaction 公式定義");
    expect(fterm.normalized_code).toBe("4C083AA01");
  });

  it.each([
    ["/api/v1/lookup?scheme=cpc&code=G06F3%2F048", 400, "INVALID_SCHEME"],
    ["/api/v1/lookup?scheme=fi&code=%20%20", 400, "INVALID_CODE"],
    ["/api/v1/lookup?scheme=fi&code=G06F3%2F048&language=fr", 400, "INVALID_LANGUAGE"],
    ["/api/v1/lookup?scheme=fi&code=G06F3%2F048&edition=8U", 400, "INVALID_EDITION"],
    ["/api/v1/lookup?scheme=fi&code=G06F3%2F048&extra=x", 400, "INVALID_QUERY"],
    [
      "/api/v1/lookup?scheme=fi&scheme=ipc&code=G06F3%2F048",
      400,
      "INVALID_QUERY",
    ],
    [
      "/api/v1/lookup?scheme=fi&code=G06F3%2F048&release=JPPM2000000",
      404,
      "RELEASE_NOT_FOUND",
    ],
    ["/api/v1/lookup?scheme=fi&code=A01B9%2F999", 404, "CLASSIFICATION_NOT_FOUND"],
  ])("returns a safe structured error for %s", async (path, status, code) => {
    const response = await request(path);
    const payload = await json(response);
    const serialized = JSON.stringify(payload);
    expect(response.status).toBe(status);
    expect(payload).toMatchObject({ error: { code } });
    expect(serialized).not.toMatch(/[A-Z]:\\|\/Users\/|stack/iu);
  });

  it("returns 503 when a manifest points to a missing chunk", async () => {
    const response = await request("/api/v1/lookup?scheme=fi&code=Z99Z99%2F999");
    expect(response.status).toBe(503);
    expect(await json(response)).toMatchObject({ error: { code: "RELEASE_UNAVAILABLE" } });
  });
});

describe("document API", () => {
  it("selects exact pages and sections within two R2 reads", async () => {
    const pageResponse = await request(
      "/api/v1/documents/doc-aaaaaaaaaaaaaaaaaaaaaaaa?page=2",
    );
    const page = await json(pageResponse);
    const section = await json(
      await request("/api/v1/documents/doc-aaaaaaaaaaaaaaaaaaaaaaaa?section=1"),
    );

    expect(pageResponse.status).toBe(200);
    expect(pageResponse.headers.get("Server-Timing")).toBe('pmgs-r2;desc="2 reads"');
    expect(page.segments).toEqual([
      expect.objectContaining({ sequence_number: 2, text: "Synthetic page two" }),
    ]);
    expect(section.segments).toEqual([
      expect.objectContaining({ sequence_number: 1, text: "Synthetic page one" }),
    ]);
  });

  it.each([
    ["/api/v1/documents/not-a-document", 404],
    ["/api/v1/documents/doc-bbbbbbbbbbbbbbbbbbbbbbbb", 404],
    ["/api/v1/documents/doc-aaaaaaaaaaaaaaaaaaaaaaaa?page=1&section=1", 400],
    ["/api/v1/documents/doc-aaaaaaaaaaaaaaaaaaaaaaaa?page=9", 404],
  ])("handles document errors for %s", async (path, status) => {
    const response = await request(path);
    expect(response.status).toBe(status);
    expect(await json(response)).toHaveProperty("error");
  });
});

describe("static and negotiated routes", () => {
  it("streams HTML by default and pre-generated Markdown on Accept", async () => {
    const html = await request("/ja/classification/G06F3");
    const markdown = await request("/ja/classification/G06F3", {
      headers: { Accept: "text/markdown" },
    });

    expect(html.status).toBe(200);
    expect(html.headers.get("Content-Type")).toContain("text/html");
    expect(html.headers.get("Vary")).toContain("Accept");
    expect(await html.text()).toContain("FI interaction 公式定義");
    expect(markdown.headers.get("Content-Type")).toContain("text/markdown");
    const markdownBody = await markdown.text();
    expect(markdownBody).toContain("# FI G06F3/048");
    expect(markdownBody).toContain("合成テストデータを変換して作成しています");
  });

  it("serves discovery, immutable release JSON, conditional GET, HEAD, and WebMCP", async () => {
    const index = await request("/");
    const indexBody = await index.text();
    expect(indexBody).toContain("/assets/webmcp.js");
    expect(indexBody).toContain("公的機関が運営する公式サービスではありません");

    const englishIndex = await request("/en/");
    expect(englishIndex.status).toBe(200);
    expect(await englishIndex.text()).toContain(
      "not an official service operated by a public authority",
    );

    const japaneseLlms = await request("/llms.txt");
    expect(await japaneseLlms.text()).toContain("合成テストデータを変換して作成しています");
    const englishLlms = await request("/llms.en.txt");
    expect(await englishLlms.text()).toContain("generated from transformed synthetic test data");

    const release = await request(`/releases/JPPM2099001/manifest.json`);
    expect(release.headers.get("Cache-Control")).toContain("immutable");
    expect((await json(release)).release_id).toBe("JPPM2099001");

    const style = await request("/assets/style.css");
    const etag = style.headers.get("ETag");
    expect(etag).toBeTruthy();
    const unchanged = await request("/assets/style.css", {
      headers: { "If-None-Match": etag ?? "" },
    });
    expect(unchanged.status).toBe(304);

    const head = await request("/openapi.json", { method: "HEAD" });
    expect(head.status).toBe(200);
    expect(await head.text()).toBe("");
    expect(head.headers.get("Content-Length")).toBeTruthy();

    const webmcp = await request("/assets/webmcp.js");
    expect(webmcp.status).toBe(200);
    expect(await webmcp.text()).toContain("lookup_patent_classification");
  });

  it("redirects non-canonical 001 pages and rejects traversal-shaped routes", async () => {
    const redirect = await request("/ja/classification/G06F3/001", { redirect: "manual" });
    expect(redirect.status).toBe(308);
    expect(redirect.headers.get("Location")).toBe(`${ORIGIN}/ja/classification/G06F3`);

    expect(
      (await request("/releases/JPPM2099001/groups/classification/%2Fetc/manifest.json"))
        .status,
    ).toBe(404);
  });
});

describe("HTTP policy", () => {
  it("handles preflight, methods, CORS, and security headers", async () => {
    const options = await request("/api/v1/lookup", { method: "OPTIONS" });
    const post = await request("/api/v1/lookup", { method: "POST" });

    expect(options.status).toBe(204);
    expect(options.headers.get("Access-Control-Allow-Origin")).toBe("*");
    expect(post.status).toBe(405);
    expect(post.headers.get("Allow")).toContain("GET");
    expect(post.headers.get("Content-Security-Policy")).toContain("default-src 'none'");
    expect(post.headers.get("Strict-Transport-Security")).toContain("max-age=31536000");
    expect(post.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(post.headers.get("Referrer-Policy")).toBe("no-referrer");
  });
});

describe("bounded lookup load", () => {
  it("parses a large group chunk while preserving the two-read budget", async () => {
    const bytes = await seedLargeLookupFixture();
    const start = performance.now();
    const response = await request("/api/v1/lookup?scheme=fi&code=A01B1%2F1199");
    const elapsed = performance.now() - start;
    const payload = await json(response);

    expect(bytes).toBeGreaterThan(512 * 1024);
    expect(response.status).toBe(200);
    expect(response.headers.get("Server-Timing")).toBe('pmgs-r2;desc="2 reads"');
    expect(payload.normalized_code).toBe("A01B1/1199");
    expect(elapsed).toBeLessThan(250);
  });
});

it("uses the configured synthetic R2 binding", () => {
  expect(env.CURRENT_RELEASE).toBe("JPPM2099001");
});
