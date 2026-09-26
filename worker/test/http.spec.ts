import { describe, expect, it } from "vitest";

import { matchesIfNoneMatch, selectPageFormat } from "../src/http";

describe("HTTP representation helpers", () => {
  it.each([
    [null, '"current"', false],
    ["*", '"current"', true],
    ['"current"', '"current"', true],
    ['W/"current"', '"current"', true],
    ['"current"', 'W/"current"', true],
    ['"other", W/"current"', '"current"', true],
    ['W/"other"', '"current"', false],
    ['"CURRENT"', '"current"', false],
    ['W/"part,tag", "other"', '"part,tag"', true],
    ['"part,tag"', '"tag"', false],
    ['"current"garbage', '"current"', false],
    ['garbage, "current"', '"current"', false],
    ['"other" "current"', '"current"', false],
    ['"other""current"', '"current"', false],
    ['"current", W/', '"current"', false],
    ['*, "current"', '"current"', false],
    [', W/"current", ,', '"current"', true],
  ])("compares If-None-Match %s with %s", (header, etag, expected) => {
    expect(matchesIfNoneMatch(header, etag)).toBe(expected);
  });

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
    ["text/html;q=0.8, text/html;charset=utf-8;q=0.4, text/markdown;q=0.6", "markdown"],
    ["text/html;q=0;level=1, text/markdown;q=0.5", "markdown"],
    ["text/html;q=0, text/markdown;q=0", "html"],
    ["application/json", "html"],
  ] as const)("selects %s as %s", (accept, expected) => {
    expect(selectPageFormat(accept)).toBe(expected);
  });

});
