type ToolRegistrar = Pick<WebMCP.ModelContext, "registerTool">;
type FetchFunction = typeof fetch;

interface LookupInput {
  scheme: "fi" | "fterm" | "ipc";
  code: string;
  release?: string;
  edition?: string;
  version?: string;
  language?: "ja" | "en";
  relation_limit?: number;
  relation_offset?: number;
}

function isLookupInput(value: Record<string, unknown>): value is Record<string, unknown> & LookupInput {
  return (
    (value.scheme === "fi" || value.scheme === "fterm" || value.scheme === "ipc") &&
    typeof value.code === "string" &&
    value.code.trim().length > 0 &&
    value.code.length <= 128 &&
    (value.release === undefined ||
      (typeof value.release === "string" && value.release.length >= 1 && value.release.length <= 64)) &&
    (value.edition === undefined ||
      (value.scheme === "ipc" && typeof value.edition === "string" && value.edition.length <= 64)) &&
    (value.version === undefined ||
      (value.scheme === "ipc" &&
        typeof value.version === "string" &&
        /^(?:[0-9]{4}\.[0-9]{2}|\([0-9]{4}\.[0-9]{2}\))$/u.test(value.version.trim()))) &&
    (value.language === undefined || value.language === "ja" || value.language === "en")
    && (value.relation_limit === undefined ||
      (typeof value.relation_limit === "number" && Number.isInteger(value.relation_limit) &&
        value.relation_limit >= 1 && value.relation_limit <= 200))
    && (value.relation_offset === undefined ||
      (typeof value.relation_offset === "number" && Number.isInteger(value.relation_offset) &&
        value.relation_offset >= 0))
  );
}

function toolResult(payload: unknown, isError: boolean): Record<string, unknown> {
  return {
    content: [{ type: "text", text: JSON.stringify(payload) }],
    structuredContent: payload,
    isError,
  };
}

export async function registerPmgsWebMcp(
  modelContext: ToolRegistrar | undefined,
  fetchFunction: FetchFunction = fetch,
): Promise<boolean> {
  if (modelContext === undefined) {
    return false;
  }
  try {
    await modelContext.registerTool({
      name: "lookup_patent_classification",
      title: "Look up a JPO-provided patent classification",
      description:
        "Read one exact FI, F-term, or IPC definition from the published PMGS release. " +
        "Returns JPO-provided text and source lineage without AI summary or classification inference.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        properties: {
          scheme: {
            type: "string",
            enum: ["fi", "fterm", "ipc"],
            description: "Patent classification scheme.",
          },
          code: {
            type: "string",
            minLength: 1,
            maxLength: 128,
            description: "Exact patent classification code; spacing is normalized.",
          },
          release: {
            type: "string",
            minLength: 1,
            maxLength: 64,
            default: "current",
            description: "Published PMGS release identifier or current.",
          },
          edition: {
            type: "string",
            maxLength: 64,
            description: "IPC edition selector; supported only when scheme is ipc.",
          },
          version: {
            type: "string",
            pattern: "^(?:[0-9]{4}\\.[0-9]{2}|\\([0-9]{4}\\.[0-9]{2}\\))$",
            description: "IPC revision version (YYYY.MM); supported only for IPC.",
          },
          language: {
            type: "string",
            enum: ["ja", "en"],
            default: "ja",
            description: "JPO-provided language values to return.",
          },
          relation_limit: {
            type: "integer",
            minimum: 1,
            maximum: 200,
            default: 50,
          },
          relation_offset: {
            type: "integer",
            minimum: 0,
            default: 0,
          },
        },
        required: ["scheme", "code"],
      },
      annotations: {
        readOnlyHint: true,
        untrustedContentHint: true,
      },
      async execute(input: Record<string, unknown>) {
        if (!isLookupInput(input)) {
          return toolResult(
            { error: { code: "INVALID_INPUT", message: "invalid lookup arguments" } },
            true,
          );
        }
        const parameters = new URLSearchParams({
          scheme: input.scheme,
          code: input.code,
          release: input.release ?? "current",
          language: input.language ?? "ja",
        });
        if (input.edition !== undefined) parameters.set("edition", input.edition);
        if (input.version !== undefined) parameters.set("version", input.version);
        if (input.relation_limit !== undefined) {
          parameters.set("relation_limit", String(input.relation_limit));
        }
        if (input.relation_offset !== undefined) {
          parameters.set("relation_offset", String(input.relation_offset));
        }
        let response: Response;
        try {
          response = await fetchFunction(`/api/v1/lookup?${parameters.toString()}`, {
            method: "GET",
            headers: { Accept: "application/json" },
            credentials: "omit",
          });
        } catch {
          return toolResult(
            { error: { code: "NETWORK_ERROR", message: "PMGS lookup could not be reached" } },
            true,
          );
        }
        let payload: unknown;
        try {
          payload = await response.json();
        } catch {
          return toolResult(
            { error: { code: "INVALID_RESPONSE", message: "PMGS lookup returned invalid JSON" } },
            true,
          );
        }
        return toolResult(payload, !response.ok);
      },
    });
    return true;
  } catch {
    return false;
  }
}

if (typeof document !== "undefined") {
  void registerPmgsWebMcp(document.modelContext);
}
