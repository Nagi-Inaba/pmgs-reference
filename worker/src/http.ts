export type PageFormat = "html" | "markdown";

interface MediaRange {
  type: string;
  subtype: string;
  quality: number;
  order: number;
}

const REPRESENTATIONS: Readonly<Record<PageFormat, readonly [string, string]>> = {
  html: ["text", "html"],
  markdown: ["text", "markdown"],
};

function parseQuality(raw: string): number {
  const parsed = Number(raw.trim().replace(/^"|"$/gu, ""));
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
    let quality = 1;
    for (const rawParameter of rawParameters) {
      const [rawName, rawValue] = rawParameter.split("=", 2);
      if (rawName?.trim().toLowerCase() === "q") {
        quality = rawValue === undefined ? 0 : parseQuality(rawValue);
        break;
      }
    }
    ranges.push({ type: rawType, subtype: rawSubtype, quality, order });
  }
  return ranges;
}

function matchSpecificity(range: MediaRange, type: string, subtype: string): number {
  if (range.type === type && range.subtype === subtype) return 2;
  if (range.type === type && range.subtype === "*") return 1;
  if (range.type === "*" && range.subtype === "*") return 0;
  return -1;
}

function representationQuality(ranges: MediaRange[], format: PageFormat): number {
  const [type, subtype] = REPRESENTATIONS[format];
  let selected: MediaRange | null = null;
  let selectedSpecificity = -1;
  for (const range of ranges) {
    const specificity = matchSpecificity(range, type, subtype);
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
