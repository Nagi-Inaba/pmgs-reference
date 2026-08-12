import { env } from "cloudflare:workers";

const RELEASE = "JPPM2099001";
const BASE_URL = "https://pmgs.example.test";
const NOTICE_JA =
  "Synthetic test fixture https://example.test/synthetic-pmgs " +
  "このページは、合成テストデータを変換して作成しています。 " +
  "このページは、公的機関が運営する公式サービスではありません。";
const NOTICE_EN =
  "Synthetic test fixture https://example.test/synthetic-pmgs " +
  "This page is generated from transformed synthetic test data. " +
  "This is not an official service operated by a public authority.";
const SOURCE = {
  source_id: "src-synthetic",
  title: "synthetic.csv",
  relative_id: "FI/FI/synthetic.csv",
  owner: "Test Fixture",
  original_url: "https://example.test/synthetic-pmgs",
  sha256: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
  attribution: "Copyright (C) TEST 2026",
};

function record(
  scheme: "fi" | "fterm" | "ipc",
  code: string,
  edition: string | null,
  pagePath: string,
  text: string,
) {
  const lookup = `${scheme}\u001f${edition ?? ""}\u001f${code}`;
  const fragment = `${scheme}-${code.replace("/", "_2F")}`;
  const version = scheme === "ipc" ? "2021.01" : null;
  const labels = [
    {
      kind: "label",
      language: "ja",
      text: `${text} 日本語`,
      provenance: "official",
      source_id: SOURCE.source_id,
      locator: "row:1",
    },
    {
      kind: "label",
      language: "en",
      text: `${text} English`,
      provenance: "official",
      source_id: SOURCE.source_id,
      locator: "row:1",
    },
  ];
  const texts = [
    {
      kind: "definition",
      language: "ja",
      text: `${text} 公式定義`,
      provenance: "official",
      source_id: SOURCE.source_id,
      locator: "row:1",
    },
    {
      kind: "definition",
      language: "en",
      text: `${text} official definition`,
      provenance: "official",
      source_id: SOURCE.source_id,
      locator: "row:1",
    },
  ];
  const properties = [
    {
      name: "scope",
      value: "synthetic",
      language: null,
      provenance: "official",
      source_id: SOURCE.source_id,
      locator: "row:1",
    },
  ];
  const documents = [
    {
      document_id: "doc-aaaaaaaaaaaaaaaaaaaaaaaa",
      kind: "fi_handbook",
      language: "ja",
      title: "Synthetic handbook",
      page_count: 2,
      link_type: "fi_handbook",
      source_id: SOURCE.source_id,
      locator: "row:1",
    },
  ];
  const relations = [
    {
      type: "parent",
      scheme,
      code: `${code}-PARENT`,
      edition,
      version,
      source_id: SOURCE.source_id,
      locator: "row:1",
    },
    {
      type: "child",
      scheme,
      code: `${code}-CHILD`,
      edition,
      version,
      source_id: SOURCE.source_id,
      locator: "row:2",
    },
  ];
  return {
    schema_version: "2.0",
    release_id: RELEASE,
    reference_date: "2026-01-01",
    lookup_key: lookup,
    scheme,
    edition,
    code,
    normalized_code: code,
    record_status: "canonical",
    match_status: "exact",
    version,
    valid_from: (version === null ? null : "2021-01-01") as string | null,
    valid_to: (version === null ? null : "9999-12-31") as string | null,
    available_versions: [
      { version, valid_from: null as string | null, valid_to: null as string | null },
    ],
    labels,
    texts,
    properties,
    relations,
    relation_count: relations.length,
    relation_offset: 0,
    relation_limit: 50,
    next_relation_offset: null,
    documents,
    sources: [SOURCE],
    revision_records: [
      {
        version,
        valid_from: (version === null ? null : "2021-01-01") as string | null,
        valid_to: (version === null ? null : "9999-12-31") as string | null,
        labels,
        texts,
        properties,
        relations,
        documents,
        sources: [SOURCE],
      },
    ],
    fragment,
    canonical_urls: {
      ja: `${BASE_URL}/ja/${pagePath}#${fragment}`,
      en: `${BASE_URL}/en/${pagePath}#${fragment}`,
    },
  };
}

const FI = record("fi", "G06F3/048", null, "classification/G06F3", "FI interaction");
const IPC_8U = record(
  "ipc",
  "G06F3/048",
  "8U",
  "classification/G06F3/002",
  "IPC current interaction",
);
IPC_8U.available_versions.unshift({
  version: "2006.01",
  valid_from: "2006-01-01",
  valid_to: "2020-12-31",
});
IPC_8U.revision_records.unshift({
  ...IPC_8U.revision_records[0]!,
  version: "2006.01",
  valid_from: "2006-01-01",
  valid_to: "2020-12-31",
  texts: IPC_8U.texts.map((item) => ({ ...item, text: `${item.text} legacy` })),
});
const IPC_7E = record("ipc", "G06F3/048", "7E", "ipc/7E/G06F3", "IPC legacy interaction");
const IPC_EXPIRED = record(
  "ipc",
  "G06F3/050",
  "8U",
  "classification/G06F3/003",
  "IPC expired interaction",
);
IPC_EXPIRED.match_status = "not_valid_at_release";
IPC_EXPIRED.version = null;
IPC_EXPIRED.valid_from = null;
IPC_EXPIRED.valid_to = null;
IPC_EXPIRED.labels = [];
IPC_EXPIRED.texts = [];
IPC_EXPIRED.properties = [];
IPC_EXPIRED.relations = [];
IPC_EXPIRED.documents = [];
IPC_EXPIRED.available_versions = [
  { version: "2006.01", valid_from: "2006-01-01", valid_to: "2020-12-31" },
];
IPC_EXPIRED.revision_records = [
  {
    ...IPC_EXPIRED.revision_records[0]!,
    version: "2006.01",
    valid_from: "2006-01-01",
    valid_to: "2020-12-31",
  },
];
const FTERM = record("fterm", "4C083AA01", null, "fterm/4C083", "F-term cosmetic");

const OBJECTS: Record<string, { body: string; contentType: string }> = {
  "index.html": {
    body: `<!doctype html><html><body><h1>PMGS Reference</h1><p>${NOTICE_JA}</p><script src="/assets/webmcp.js" defer></script></body></html>`,
    contentType: "text/html; charset=utf-8",
  },
  "index.en.html": {
    body: `<!doctype html><html lang="en"><body><h1>PMGS Reference</h1><p>${NOTICE_EN}</p></body></html>`,
    contentType: "text/html; charset=utf-8",
  },
  "openapi.json": {
    body: JSON.stringify({ openapi: "3.1.0" }),
    contentType: "application/json; charset=utf-8",
  },
  "llms.txt": {
    body: `# PMGS Reference\n\n${NOTICE_JA}\n`,
    contentType: "text/plain; charset=utf-8",
  },
  "llms.en.txt": {
    body: `# PMGS Reference\n\n${NOTICE_EN}\n`,
    contentType: "text/plain; charset=utf-8",
  },
  "robots.txt": {
    body: "User-agent: *\nContent-Signal: search=yes, ai-input=yes, ai-train=no\nAllow: /\n",
    contentType: "text/plain; charset=utf-8",
  },
  "sitemap.xml": {
    body: '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>',
    contentType: "application/xml; charset=utf-8",
  },
  "assets/style.css": { body: "body{color:#111}", contentType: "text/css; charset=utf-8" },
  "api/v1/releases.json": {
    body: JSON.stringify({ current_release: RELEASE, releases: [RELEASE] }),
    contentType: "application/json; charset=utf-8",
  },
  "api/v1/coverage.json": {
    body: JSON.stringify({ "classification.unique_public": 4 }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/manifest.json`]: {
    body: JSON.stringify({ schema_version: "2.0", release_id: RELEASE, objects: [] }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/coverage.json`]: {
    body: JSON.stringify({ "classification.unique_public": 4 }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/publication-policy.json`]: {
    body: JSON.stringify({
      schema_version: "1.0",
      release_id: RELEASE,
      sources: [
        {
          source_id: "synthetic-pmgs",
          owner: "Test Fixture",
          source_url: "https://example.test/synthetic-pmgs",
          attribution: "Copyright (C) TEST 2026",
          processing_notice: {
            ja: "このページは、合成テストデータを変換して作成しています。",
            en: "This page is generated from transformed synthetic test data.",
          },
          non_affiliation_notice: {
            ja: "このページは、公的機関が運営する公式サービスではありません。",
            en: "This is not an official service operated by a public authority.",
          },
        },
      ],
    }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/groups/classification/G06F3/manifest.json`]: {
    body: JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      group_kind: "classification",
      edition: null,
      group_key: "G06F3",
      record_count: 3,
      chunks: [
        {
          chunk_id: "001",
          first_lookup_key: FI.lookup_key,
          last_lookup_key: FI.lookup_key,
          record_count: 1,
          json_key: `releases/${RELEASE}/groups/classification/G06F3/001.json`,
          json_bytes: 1,
          json_sha256: "A".repeat(64),
        },
        {
          chunk_id: "002",
          first_lookup_key: IPC_8U.lookup_key,
          last_lookup_key: IPC_8U.lookup_key,
          record_count: 1,
          json_key: `releases/${RELEASE}/groups/classification/G06F3/002.json`,
          json_bytes: 1,
          json_sha256: "B".repeat(64),
        },
        {
          chunk_id: "003",
          first_lookup_key: IPC_EXPIRED.lookup_key,
          last_lookup_key: IPC_EXPIRED.lookup_key,
          record_count: 1,
          json_key: `releases/${RELEASE}/groups/classification/G06F3/003.json`,
          json_bytes: 1,
          json_sha256: "C".repeat(64),
        },
      ],
    }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/groups/classification/G06F3/001.json`]: {
    body: JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      chunk_id: "001",
      records: [FI],
    }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/groups/classification/G06F3/002.json`]: {
    body: JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      chunk_id: "002",
      records: [IPC_8U],
    }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/groups/classification/G06F3/003.json`]: {
    body: JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      chunk_id: "003",
      records: [IPC_EXPIRED],
    }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/groups/ipc/7E/G06F3/manifest.json`]: {
    body: JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      group_kind: "ipc",
      edition: "7E",
      group_key: "G06F3",
      record_count: 1,
      chunks: [
        {
          chunk_id: "001",
          first_lookup_key: IPC_7E.lookup_key,
          last_lookup_key: IPC_7E.lookup_key,
          record_count: 1,
          json_key: `releases/${RELEASE}/groups/ipc/7E/G06F3/001.json`,
          json_bytes: 1,
          json_sha256: "C".repeat(64),
        },
      ],
    }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/groups/ipc/7E/G06F3/001.json`]: {
    body: JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      chunk_id: "001",
      records: [IPC_7E],
    }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/groups/fterm/4C083/manifest.json`]: {
    body: JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      group_kind: "fterm",
      edition: null,
      group_key: "4C083",
      record_count: 1,
      chunks: [
        {
          chunk_id: "001",
          first_lookup_key: FTERM.lookup_key,
          last_lookup_key: FTERM.lookup_key,
          record_count: 1,
          json_key: `releases/${RELEASE}/groups/fterm/4C083/001.json`,
          json_bytes: 1,
          json_sha256: "D".repeat(64),
        },
      ],
    }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/groups/fterm/4C083/001.json`]: {
    body: JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      chunk_id: "001",
      records: [FTERM],
    }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/groups/classification/Z99Z99/manifest.json`]: {
    body: JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      group_kind: "classification",
      edition: null,
      group_key: "Z99Z99",
      record_count: 1,
      chunks: [
        {
          chunk_id: "001",
          first_lookup_key: "fi\u001f\u001fZ99Z99/999",
          last_lookup_key: "fi\u001f\u001fZ99Z99/999",
          record_count: 1,
          json_key: `releases/${RELEASE}/groups/classification/Z99Z99/001.json`,
          json_bytes: 1,
          json_sha256: "E".repeat(64),
        },
      ],
    }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/documents/doc-aaaaaaaaaaaaaaaaaaaaaaaa/manifest.json`]: {
    body: JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      document_id: "doc-aaaaaaaaaaaaaaaaaaaaaaaa",
      kind: "ipc_definition",
      language: "ja",
      site_language: "ja",
      title: "Synthetic definition",
      page_count: 2,
      metadata: {},
      segment_count: 2,
      source: SOURCE,
      chunks: [
        {
          chunk_id: "001",
          first_sequence: 1,
          last_sequence: 2,
          pages: [1, 2],
          segment_count: 2,
          json_key: `releases/${RELEASE}/documents/doc-aaaaaaaaaaaaaaaaaaaaaaaa/001.json`,
          json_bytes: 1,
          json_sha256: "F".repeat(64),
          url: `${BASE_URL}/ja/documents/doc-aaaaaaaaaaaaaaaaaaaaaaaa`,
        },
      ],
    }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/documents/doc-aaaaaaaaaaaaaaaaaaaaaaaa/001.json`]: {
    body: JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      document_id: "doc-aaaaaaaaaaaaaaaaaaaaaaaa",
      chunk_id: "001",
      segments: [
        {
          sequence_number: 1,
          locator: "page:1",
          heading: "Page 1",
          text: "Synthetic page one",
          source_locator: "page:1",
          related_classifications: [],
        },
        {
          sequence_number: 2,
          locator: "page:2",
          heading: "Page 2",
          text: "Synthetic page two",
          source_locator: "page:2",
          related_classifications: [],
        },
      ],
    }),
    contentType: "application/json; charset=utf-8",
  },
  [`releases/${RELEASE}/site/ja/classification/G06F3/001.html`]: {
    body: `<!doctype html><html><body><p>${NOTICE_JA}</p><article id="fi-G06F3_2F048">FI interaction 公式定義</article></body></html>`,
    contentType: "text/html; charset=utf-8",
  },
  [`releases/${RELEASE}/site/ja/classification/G06F3/001.md`]: {
    body: `# FI G06F3/048\n\n${NOTICE_JA}\n\nFI interaction 公式定義\n`,
    contentType: "text/markdown; charset=utf-8",
  },
};

export async function seedFixture(): Promise<void> {
  await Promise.all(
    Object.entries(OBJECTS).map(async ([key, value]) => {
      await env.PMGS_BUCKET.put(key, value.body, {
        httpMetadata: { contentType: value.contentType },
      });
    }),
  );
}

export async function seedPagedIpcFixture(additionalRelations = 65): Promise<number> {
  const candidate = structuredClone(IPC_8U);
  const revision = candidate.revision_records.find(
    (item) => item.version === candidate.version,
  );
  const template = revision?.relations[0];
  if (revision === undefined || template === undefined) {
    throw new Error("IPC fixture has no reference-date revision relation");
  }
  revision.relations.push(
    ...Array.from({ length: additionalRelations }, (_, index) => ({
      ...template,
      code: `G06F3/${100 + index}`,
      locator: `paging:${index}`,
    })),
  );
  candidate.relations = revision.relations.slice(0, 50);
  candidate.relation_count = revision.relations.length;
  const pagedCandidate: Omit<typeof candidate, "next_relation_offset"> & {
    next_relation_offset: number | null;
  } = {
    ...candidate,
    next_relation_offset: candidate.relation_count > 50 ? 50 : null,
  };
  await env.PMGS_BUCKET.put(
    `releases/${RELEASE}/groups/classification/G06F3/002.json`,
    JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      chunk_id: "002",
      records: [pagedCandidate],
    }),
    { httpMetadata: { contentType: "application/json; charset=utf-8" } },
  );
  return candidate.relation_count;
}

export async function seedMalformedClassificationFixture(
  defect: "revision_relation" | "storage_schema",
): Promise<void> {
  const candidate = structuredClone(IPC_8U) as unknown as {
    schema_version: string;
    revision_records: Array<{ relations: unknown[] }>;
  };
  if (defect === "revision_relation") {
    candidate.revision_records[0]!.relations = [{}];
  } else {
    candidate.schema_version = "9.9";
  }
  await env.PMGS_BUCKET.put(
    `releases/${RELEASE}/groups/classification/G06F3/002.json`,
    JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      chunk_id: "002",
      records: [candidate],
    }),
    { httpMetadata: { contentType: "application/json; charset=utf-8" } },
  );
}

export async function seedLargeLookupFixture(recordCount = 1_200): Promise<number> {
  const records = Array.from({ length: recordCount }, (_, index) => {
    const code = `A01B1/${String(index).padStart(4, "0")}`;
    return record("fi", code, null, "classification/A01B1", `Synthetic record ${index}`);
  });
  const first = records[0];
  const last = records.at(-1);
  if (first === undefined || last === undefined) {
    throw new Error("large fixture has no records");
  }
  const chunkKey = `releases/${RELEASE}/groups/classification/A01B1/001.json`;
  const body = JSON.stringify({
    schema_version: "2.0",
    release_id: RELEASE,
    chunk_id: "001",
    records,
  });
  await env.PMGS_BUCKET.put(
    `releases/${RELEASE}/groups/classification/A01B1/manifest.json`,
    JSON.stringify({
      schema_version: "2.0",
      release_id: RELEASE,
      group_kind: "classification",
      edition: null,
      group_key: "A01B1",
      record_count: records.length,
      chunks: [
        {
          chunk_id: "001",
          first_lookup_key: first.lookup_key,
          last_lookup_key: last.lookup_key,
          record_count: records.length,
          json_key: chunkKey,
          json_bytes: new TextEncoder().encode(body).byteLength,
          json_sha256: "0".repeat(64),
        },
      ],
    }),
    { httpMetadata: { contentType: "application/json; charset=utf-8" } },
  );
  await env.PMGS_BUCKET.put(chunkKey, body, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
  });
  return new TextEncoder().encode(body).byteLength;
}
