import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("the Kairay brand logo is a bundled PNG asset", async () => {
  const bytes = await readFile("public/assets/kairay-golf-logo.png");
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.ok(bytes.length > 1_000, "the logo must not be an empty placeholder");
});

test("every browser-facing logo URL carries the PNG content version", async () => {
  const expected = "/assets/kairay-golf-logo.png?v=4bf743d2";
  const [brandMark, indexHtml] = await Promise.all([
    readFile("src/components/BrandMark.tsx", "utf8"),
    readFile("index.html", "utf8"),
  ]);

  assert.ok(brandMark.includes(expected), "the in-app logo must bypass stale browser caches");
  assert.equal(
    indexHtml.split(expected).length - 1,
    2,
    "favicon and apple-touch-icon must use the same versioned PNG",
  );
});
