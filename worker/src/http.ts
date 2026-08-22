export type PageFormat = "html" | "markdown";

interface MediaRange {
  type: string;
  subtype: string;
  parameters: Readonly<Record<string, string>>;
  quality: number;
  order: number;
}

interface Representation {
  type: string;
  subtype: string;
  parameters: Readonly<Record<string, string>>;
}

const REPRESENTATIONS: Readonly<Record<PageFormat, Representation>> = {
  html: { type: "text", subtype: "html", parameters: { charset: "utf-8" } },
  markdown: { type: "text", subtype: "markdown", parameters: { charset: "utf-8" } },
};

function unquote(raw: string): string {
  const value = raw.trim();
  return value.length >= 2 && value.startsWith('"') && value.endsWith('"')
    ? value.slice(1, -1)
    : value;
}

function parseQuality(raw: string): number {
  const parsed = Number(unquote(raw));
  return Number.isFinite(parsed) && parsed >= 0 && parsed <= 1 ? parsed : 0;
}

function parseAccept(value: string): MediaRange[] {
  const ranges: MediaRange[] = [];
  for (const [order, rawRange] of value.split(",").entries()) {
    const [rawMediaType, ...rawParameters] = rawRange.split(";");
    const [rawType, rawSubtype, ...extra] = (rawMediaType ?? "")
      .trim()
      .toLowerCase()
      .split("/");
    if (rawType === undefined || rawSubtype === undefined || extra.length > 0) {
      continue;
    }

    const parameters: Record<string, string> = {};
    let quality = 1;
    let sawQuality = false;
    for (const rawParameter of rawParameters) {
      const separator = rawParameter.indexOf("=");
      const rawName = separator < 0 ? rawParameter : rawParameter.slice(0, separator);
      const rawValue = separator < 0 ? "" : rawParameter.slice(separator + 1);
      const name = rawName.trim().toLowerCase();
      if (name === "") continue;
      if (!sawQuality && name === "q") {
        quality = rawValue === "" ? 0 : parseQuality(rawValue);
        sawQuality = true;
        continue;
      }
      if (!sawQuality) {
        const parameterValue = unquote(rawValue);
        parameters[name] = name === "charset" ? parameterValue.toLowerCase() : parameterValue;
      }
      // Parameters after q are accept extensions and do not constrain the media range.
    }
    ranges.push({ type: rawType, subtype: rawSubtype, parameters, quality, order });
  }
  return ranges;
}

function parametersMatch(range: MediaRange, representation: Representation): boolean {
  return Object.entries(range.parameters).every(
    ([name, value]) => representation.parameters[name] === value,
  );
}

function matchSpecificity(range: MediaRange, representation: Representation): number {
  if (!parametersMatch(range, representation)) return -1;
  const parameterSpecificity = Object.keys(range.parameters).length;
  if (range.type === representation.type && range.subtype === representation.subtype) {
    return 2000 + parameterSpecificity;
  }
  if (range.type === representation.type && range.subtype === "*") {
    return 1000 + parameterSpecificity;
  }
  if (range.type === "*" && range.subtype === "*") {
    return parameterSpecificity;
  }
  return -1;
}

function representationQuality(ranges: MediaRange[], format: PageFormat): number {
  const representation = REPRESENTATIONS[format];
  let selected: MediaRange | null = null;
  let selectedSpecificity = -1;
  for (const range of ranges) {
    const specificity = matchSpecificity(range, representation);
    if (specificity < 0) continue;
    if (
      selected === null ||
      specificity > selectedSpecificity ||
      (specificity === selectedSpecificity && range.quality > selected.quality) ||
      (specificity === selectedSpecificity &&
        range.quality === selected.quality &&
        range.order < selected.order)
    ) {
      selected = range;
      selectedSpecificity = specificity;
    }
  }
  return selected?.quality ?? 0;
}

export function selectPageFormat(accept: string): PageFormat {
  if (accept.trim() === "") return "html";
  const ranges = parseAccept(accept);
  const htmlQuality = representationQuality(ranges, "html");
  const markdownQuality = representationQuality(ranges, "markdown");
  return markdownQuality > htmlQuality ? "markdown" : "html";
}

export function allowedMethods(api: boolean): string {
  return api ? "GET, HEAD, OPTIONS" : "GET, HEAD";
}
