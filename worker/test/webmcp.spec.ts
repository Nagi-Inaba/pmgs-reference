import { describe, expect, it, vi } from "vitest";

import { registerPmgsWebMcp } from "../webmcp/webmcp";

describe("optional WebMCP registration", () => {
  it("does nothing in unsupported browsers", async () => {
    const fetchFunction = vi.fn<typeof fetch>();
    expect(await registerPmgsWebMcp(undefined, fetchFunction)).toBe(false);
    expect(fetchFunction).not.toHaveBeenCalled();
  });

  it("registers exactly one read-only lookup tool and returns the API record", async () => {
    let registered: WebMCP.ModelContextTool | undefined;
    const registrar = {
      async registerTool(tool: WebMCP.ModelContextTool): Promise<void> {
        registered = tool;
      },
    };
    const apiRecord = {
      schema_version: "1.0",
      release_id: "JPPM2099001",
      scheme: "fi",
      code: "G06F3/048",
    };
    const fetchFunction = vi.fn<typeof fetch>(async () => Response.json(apiRecord));

    expect(await registerPmgsWebMcp(registrar, fetchFunction)).toBe(true);
    expect(registered).toBeDefined();
    expect(registered?.name).toBe("lookup_patent_classification");
    expect(registered?.annotations).toMatchObject({
      readOnlyHint: true,
      untrustedContentHint: true,
    });
    expect(registered?.inputSchema).toMatchObject({
      required: ["scheme", "code"],
      additionalProperties: false,
    });

    const result = await registered?.execute({ scheme: "fi", code: "G06F3/048" });
    expect(result).toMatchObject({ structuredContent: apiRecord, isError: false });
    expect(fetchFunction).toHaveBeenCalledOnce();
    expect(fetchFunction.mock.calls[0]?.[0]).toContain(
      "/api/v1/lookup?scheme=fi&code=G06F3%2F048&release=current&language=ja",
    );
    expect(fetchFunction.mock.calls[0]?.[1]).toMatchObject({
      method: "GET",
      credentials: "omit",
    });
  });

  it("returns safe tool errors for invalid input, HTTP errors, and registration rejection", async () => {
    let registered: WebMCP.ModelContextTool | undefined;
    const registrar = {
      async registerTool(tool: WebMCP.ModelContextTool): Promise<void> {
        registered = tool;
      },
    };
    const fetchFunction = vi.fn<typeof fetch>(async () =>
      Response.json(
        { error: { code: "CLASSIFICATION_NOT_FOUND", message: "classification not found" } },
        { status: 404 },
      ),
    );
    await registerPmgsWebMcp(registrar, fetchFunction);

    expect(await registered?.execute({ scheme: "fi", code: "" })).toMatchObject({
      isError: true,
      structuredContent: { error: { code: "INVALID_INPUT" } },
    });
    expect(await registered?.execute({ scheme: "fi", code: "Z99Z99/999" })).toMatchObject({
      isError: true,
      structuredContent: { error: { code: "CLASSIFICATION_NOT_FOUND" } },
    });

    const rejecting = {
      async registerTool(): Promise<void> {
        throw new DOMException("disabled", "NotAllowedError");
      },
    };
    expect(await registerPmgsWebMcp(rejecting, fetchFunction)).toBe(false);
  });
});
