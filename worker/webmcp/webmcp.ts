type ToolRegistrar = Pick<WebMCP.ModelContext, "registerTool">;
type FetchFunction = typeof fetch;

interface LookupInput {
  scheme: "fi" | "fterm" | "ipc";
  code: string;
  release?: string;
  language?: "ja" | "en";
}

function isLookupInput(value: Record<string, unknown>): value is Record<string, unknown> & LookupInput {
  return (
    (value.scheme === "fi" || value.scheme === "fterm" || value.scheme === "ipc") &&
    typeof value.code === "string" &&
    value.code.trim().length > 0 &&
    value.code.length <= 128 &&
    (value.release === undefined || typeof value.release === "string") &&
    (value.language === undefined || value.language === "ja" || value.language === "en")
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
            default: "current",
            description: "Published PMGS release identifier or current.",
          },
          language: {
            type: "string",
            enum: ["ja", "en"],
            default: "ja",
            description: "JPO-provided language values to return.",
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
