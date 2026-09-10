import { createHash } from "node:crypto";

export type ExtractedValueType = "number" | "boolean" | "date" | "set";

export type ExtractionPolicy = {
  method: "JSON_PATH" | "HTML_SELECTOR" | "REGEX";
  value_path?: string;
  effective_from_path?: string;
  source_publication_date_path?: string;
  pattern?: string;
  value_group?: number;
  effective_from_group?: number;
  unit?: string;
  version: string;
};

export type SourceExtraction = {
  value: string | number | boolean | string[];
  effectiveFrom?: number;
  sourcePublicationDate?: number;
  unit: string | undefined;
  method: ExtractionPolicy["method"];
  version: string;
  sourceSnapshotHash: string;
};

/**
 * Keep a configured source binding intact across HTTP redirects.
 *
 * The seller is allowed to fetch a pinned URL, not to follow content onto an
 * unrelated host and still publish the result as if it came from the pinned
 * source.  Same-origin redirects remain usable for sources that canonicalize
 * a path or add a trailing slash.
 */
export function assertFetchedSourceOrigin(requestedUrl: string, fetchedUrl: string): void {
  let requested: URL;
  let fetched: URL;
  try {
    requested = new URL(requiredString(requestedUrl, "requested source URL"));
    fetched = new URL(requiredString(fetchedUrl, "fetched source URL"));
  } catch (error) {
    throw new Error("source URL is not a valid HTTP or HTTPS URL", { cause: error });
  }
  if (
    !["http:", "https:"].includes(requested.protocol)
    || !["http:", "https:"].includes(fetched.protocol)
    || requested.protocol !== fetched.protocol
    || requested.hostname.toLowerCase() !== fetched.hostname.toLowerCase()
    || requested.port !== fetched.port
  ) {
    throw new Error("verifier source redirected to a different origin");
  }
}

export function parseExtractionPolicy(value: unknown): ExtractionPolicy {
  if (!isObject(value)) throw new Error("verifier extraction policy must be an object");
  const method = requiredString(value.method, "extraction.method");
  if (method !== "JSON_PATH" && method !== "HTML_SELECTOR" && method !== "REGEX") {
    throw new Error("extraction.method is not supported");
  }
  const version = requiredString(value.version, "extraction.version");
  const policy: ExtractionPolicy = { method, version };
  for (const field of ["value_path", "effective_from_path", "source_publication_date_path", "pattern", "unit"] as const) {
    const fieldValue = value[field];
    if (fieldValue !== undefined) {
      policy[field] = requiredString(fieldValue, `extraction.${field}`);
    }
  }
  for (const field of ["value_group", "effective_from_group"] as const) {
    const fieldValue = value[field];
    if (fieldValue !== undefined) {
      if (typeof fieldValue !== "number" || !Number.isSafeInteger(fieldValue) || fieldValue < 1) {
        throw new Error(`extraction.${field} must be a positive integer`);
      }
      policy[field] = fieldValue;
    }
  }
  if ((method === "JSON_PATH" || method === "HTML_SELECTOR") && policy.value_path === undefined) {
    throw new Error(`extraction.value_path is required for ${method}`);
  }
  if (method === "REGEX" && policy.pattern === undefined) {
    throw new Error("extraction.pattern is required for REGEX");
  }
  return policy;
}

export function extractSource(
  sourceText: string,
  valueType: ExtractedValueType,
  policy: ExtractionPolicy,
): SourceExtraction {
  if (sourceText.trim() === "") throw new Error("verifier source was empty");
  const extracted = policy.method === "JSON_PATH"
    ? extractJson(sourceText, policy)
    : policy.method === "REGEX"
      ? extractRegex(sourceText, policy)
      : extractHtml(sourceText, policy);
  const value = parseTypedValue(extracted.value, valueType);
  const effectiveFrom = extracted.effectiveFrom === undefined
    ? undefined
    : parseTimestamp(extracted.effectiveFrom, "effective_from");
  const sourcePublicationDate = extracted.sourcePublicationDate === undefined
    ? undefined
    : parseTimestamp(extracted.sourcePublicationDate, "source_publication_date");
  return {
    value,
    effectiveFrom,
    sourcePublicationDate,
    unit: policy.unit,
    method: policy.method,
    version: requiredString(policy.version, "extraction.version"),
    sourceSnapshotHash: sha256(sourceText),
  };
}

function extractJson(
  sourceText: string,
  policy: ExtractionPolicy,
): { value: unknown; effectiveFrom?: unknown; sourcePublicationDate?: unknown } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(sourceText);
  } catch (error) {
    throw new Error("verifier source is not valid JSON", { cause: error });
  }
  return {
    value: readPath(parsed, requiredString(policy.value_path, "extraction.value_path")),
    effectiveFrom: optionalPath(parsed, policy.effective_from_path),
    sourcePublicationDate: optionalPath(parsed, policy.source_publication_date_path),
  };
}

function extractRegex(
  sourceText: string,
  policy: ExtractionPolicy,
): { value: unknown; effectiveFrom?: unknown; sourcePublicationDate?: unknown } {
  const pattern = requiredString(policy.pattern, "extraction.pattern");
  let expression: RegExp;
  try {
    expression = new RegExp(pattern, "i");
  } catch (error) {
    throw new Error("extraction.pattern is not a valid regular expression", { cause: error });
  }
  const match = expression.exec(sourceText);
  if (match === null) throw new Error("extraction pattern did not match the fetched source");
  const valueGroup = policy.value_group ?? 1;
  const rawValue = match[valueGroup];
  if (rawValue === undefined) throw new Error("extraction value group was not captured");
  const effectiveGroup = policy.effective_from_group;
  return {
    value: rawValue,
    effectiveFrom: effectiveGroup === undefined ? undefined : match[effectiveGroup],
  };
}

function extractHtml(
  sourceText: string,
  policy: ExtractionPolicy,
): { value: unknown; effectiveFrom?: unknown; sourcePublicationDate?: unknown } {
  // This deliberately supports a narrow, deterministic selector grammar.  A
  // verifier must not execute arbitrary source-provided JavaScript or CSS.
  const selector = requiredString(policy.value_path, "extraction.value_path");
  const id = selector.startsWith("#") ? selector.slice(1) : selector;
  if (!/^[A-Za-z][A-Za-z0-9_-]*$/.test(id)) {
    throw new Error("HTML_SELECTOR currently requires an id selector");
  }
  const pattern = new RegExp(`<[^>]*id=["']${escapeRegex(id)}["'][^>]*>([^<]+)<`, "i");
  const match = pattern.exec(sourceText);
  if (match === null) throw new Error(`HTML selector ${selector} did not match the fetched source`);
  return { value: match[1]?.trim() };
}

function readPath(value: unknown, path: string): unknown {
  const parts = path.split(".").map((part) => part.trim());
  if (parts.some((part) => part === "")) throw new Error("extraction path contains an empty segment");
  let current: unknown = value;
  for (const part of parts) {
    if (!isObject(current) || !(part in current)) {
      throw new Error(`extraction path ${path} was not found in the fetched source`);
    }
    current = current[part];
  }
  return current;
}

function optionalPath(value: unknown, path: string | undefined): unknown {
  return path === undefined ? undefined : readPath(value, path);
}

function parseTypedValue(
  value: unknown,
  valueType: ExtractedValueType,
): string | number | boolean | string[] {
  if (valueType === "number") {
    const parsed = typeof value === "number" ? value : typeof value === "string" ? Number(value.trim()) : NaN;
    if (!Number.isFinite(parsed)) throw new Error("extracted value is not a finite number");
    return parsed;
  }
  if (valueType === "boolean") {
    if (typeof value === "boolean") return value;
    if (value === "true") return true;
    if (value === "false") return false;
    throw new Error("extracted value is not boolean");
  }
  if (valueType === "set") {
    if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
      throw new Error("extracted value is not a string set");
    }
    return value.map((item) => item.trim());
  }
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value.trim())) {
    throw new Error("extracted value is not an ISO date");
  }
  if (Number.isNaN(Date.parse(`${value.trim()}T00:00:00Z`))) {
    throw new Error("extracted value is not a valid ISO date");
  }
  return value.trim();
}

function parseTimestamp(value: unknown, label: string): number {
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${label} must be a non-negative timestamp`);
    return value;
  }
  if (typeof value !== "string" || value.trim() === "") throw new Error(`${label} must be a timestamp or ISO date`);
  const parsed = Date.parse(value.includes("T") ? value : `${value}T00:00:00Z`);
  if (Number.isNaN(parsed)) throw new Error(`${label} must be a timestamp or ISO date`);
  return Math.floor(parsed / 1000);
}

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim() === "") throw new Error(`${label} must be a non-empty string`);
  return value.trim();
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
