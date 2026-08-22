import { describe, expect, it } from "vitest";

import { allowedMethods, selectPageFormat } from "../src/http";

describe("HTTP representation helpers", () => {
  it.each([
    ["", "html"],
    ["*/*", "html"],
    ["text/*", "html"],
    ["text/markdown", "markdown"],
    ["TEXT/MARKDOWN ; Q=1", "markdown"],
    ["text/html;q=1, text/markdown;q=0", "html"],
    ["text/html;q=0.5, text/markdown;q=1", "markdown"],
    ["text/*;q=1, text/markdown;q=0", "html"],
    ["text/html;level=1;q=1, text/markdown;q=0.5", "markdown"],
    ["text/html;charset=UTF-8;q=1, text/markdown;q=0.5", "html"],
    ["text/html;q=0;level=1, text/markdown;q=0.5", "markdown"],
    ["text/html;q=0, text/markdown;q=0", "html"],
    ["application/json", "html"],
  ] as const)("selects %s as %s", (accept, expected) => {
    expect(selectPageFormat(accept)).toBe(expected);
  });

  it("reports only methods implemented for each route class", () => {
    expect(allowedMethods(true)).toBe("GET, HEAD, OPTIONS");
    expect(allowedMethods(false)).toBe("GET, HEAD");
  });
});
