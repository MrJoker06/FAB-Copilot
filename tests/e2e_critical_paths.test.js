"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const PROJECT_ROOT = path.resolve(__dirname, "..");
const E2E_DIR = path.join(PROJECT_ROOT, "tests", "e2e");
const MANIFEST_PATH = path.join(PROJECT_ROOT, "evaluations", "e2e_critical_paths.json");
const TEST_TITLE_ID = /\btest\s*\(\s*["'](E2E-[A-Z0-9]+-\d{3})\b/g;

function extractStableIds(source, spec) {
  return [...source.matchAll(TEST_TITLE_ID)].map(match => ({ id: match[1], spec }));
}

function discoverStableIds(directory = E2E_DIR) {
  return fs.readdirSync(directory)
    .filter(name => name.endsWith(".spec.js"))
    .sort()
    .flatMap(spec => {
      const source = fs.readFileSync(path.join(directory, spec), "utf8");
      return extractStableIds(source, spec);
    });
}

test("E2E critical-path manifest exactly covers all stable desktop IDs", () => {
  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, "utf8"));
  assert.equal(manifest.schema, "fab-insight/e2e-critical-paths");
  assert.equal(manifest.version, 1);
  assert.ok(Array.isArray(manifest.critical_paths));

  const discovered = discoverStableIds();
  const expected = manifest.critical_paths;
  const expectedIds = expected.map(item => item.id);
  const discoveredIds = discovered.map(item => item.id);
  assert.equal(new Set(expectedIds).size, expectedIds.length, "manifest has duplicate stable IDs");
  assert.equal(new Set(discoveredIds).size, discoveredIds.length, "desktop specs have duplicate stable IDs");
  assert.deepEqual(
    [...expected].sort((left, right) => left.id.localeCompare(right.id)),
    [...discovered].sort((left, right) => left.id.localeCompare(right.id)),
    "manifest must exactly match every stable desktop E2E ID and its spec",
  );
});

test("critical ID discovery ignores comments and non-test string references", () => {
  const source = [
    "// E2E-SMOKE-001 must not count from a comment",
    "const stale = 'E2E-SMOKE-002';",
    "test('E2E-SMOKE-003 real declaration', async () => {});",
  ].join("\n");
  assert.deepEqual(extractStableIds(source, "fixture.spec.js"), [{ id: "E2E-SMOKE-003", spec: "fixture.spec.js" }]);
});

module.exports = { discoverStableIds, extractStableIds };
