import assert from "node:assert/strict";
import test from "node:test";

import { assertFetchedSourceOrigin, extractSource, parseExtractionPolicy } from "../src/extraction.js";

test("rejects a cross-origin redirect before accepting fetched content", () => {
  assert.doesNotThrow(() => assertFetchedSourceOrigin(
    "https://docs.example.test/retention",
    "https://docs.example.test/retention/",
  ));
  assert.throws(
    () => assertFetchedSourceOrigin(
      "https://docs.example.test/retention",
      "https://spoof.example.test/retention",
    ),
    /different origin/,
  );
});

test("extracts the value and effective date from fetched JSON content", () => {
  const result = extractSource(
    JSON.stringify({ retention_days: 90, effective_from: "2026-09-07" }),
    "number",
    parseExtractionPolicy({
      method: "JSON_PATH",
      value_path: "retention_days",
      effective_from_path: "effective_from",
      unit: "days",
      version: "retention-json-v1",
    }),
  );

  assert.equal(result.value, 90);
  assert.equal(result.effectiveFrom, 1788739200);
  assert.equal(result.unit, "days");
  assert.match(result.sourceSnapshotHash, /^[a-f0-9]{64}$/);
});

test("extracts a typed value from the fetched HTML selector", () => {
  const result = extractSource(
    '<main><span id="retention-days">365</span></main>',
    "number",
    parseExtractionPolicy({
      method: "HTML_SELECTOR",
      value_path: "#retention-days",
      unit: "days",
      version: "retention-html-v1",
    }),
  );

  assert.equal(result.value, 365);
});

test("rejects a fetched value with the wrong type", () => {
  assert.throws(
    () => extractSource(
      JSON.stringify({ retention_days: "not-a-number" }),
      "number",
      parseExtractionPolicy({
        method: "JSON_PATH",
        value_path: "retention_days",
        unit: "days",
        version: "retention-json-v1",
      }),
    ),
    /finite number/,
  );
});

test("does not allow a policy without a deterministic extraction path", () => {
  assert.throws(
    () => parseExtractionPolicy({ method: "JSON_PATH", version: "v1" }),
    /value_path is required/,
  );
});
