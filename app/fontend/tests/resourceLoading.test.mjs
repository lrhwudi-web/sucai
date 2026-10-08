import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

// Exercise the real request loop; stub only unrelated demo/auth/taxonomy dependencies.
const source = readFileSync(new URL("../src/services/materials.ts", import.meta.url), "utf8");
let javascript = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
javascript = javascript
  .replace(/import \{ mockProducts \} from "[^"]+";/, "const mockProducts = [];")
  .replace(/import\s+\{[^}]*\}\s+from\s+"\.\.\/types";/, "const DEFAULT_THEME_OPTIONS = [];")
  .replace(/import \{ normalizeProductTaxonomy \} from "[^"]+";/, "const normalizeProductTaxonomy = (brand, category) => ({ brand, category, material: '' });")
  .replace(/import \{ apiEnabled \} from "[^"]+";/, "const apiEnabled = () => true;");
assert.doesNotMatch(javascript, /^\s*import\s/m, "All unrelated imports should be replaced by test stubs.");
const { loadProducts, SessionExpiredError } = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);

test("first 40 products render before the remaining batches and all SKUs retain snapshot order", async (t) => {
  const products = Array.from({ length: 550 }, (_, index) => ({ sku: String(6000000 + index), name: `Product ${index}` }));
  const requests = [];
  const progress = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    const query = new URL(url, "https://example.test").searchParams;
    const offset = Number(query.get("offset"));
    const limit = Number(query.get("limit"));
    requests.push({ offset, limit, snapshot: query.get("catalog_snapshot") });
    if (offset) assert.equal(progress.length, requests.length - 1, "Render each completed batch before requesting the next.");
    return Response.json({ products: products.slice(offset, offset + limit), has_more: offset + limit < products.length, next_offset: offset + limit, catalog_snapshot: "stable-snapshot" });
  });
  const result = await loadProducts((batch) => progress.push(batch));
  assert.deepEqual(requests.map(({ limit }) => limit), [40, 250, 250, 250]);
  assert.equal(requests[0].snapshot, null);
  assert.ok(requests.slice(1).every(({ snapshot }) => snapshot === "stable-snapshot"));
  assert.deepEqual(progress.map((batch) => batch.length), [40, 290, 540, 550]);
  assert.deepEqual(result.products.map(({ sku }) => sku), products.map(({ sku }) => sku));
  assert.equal(progress[0].length, 40, "Later appends must not mutate previously rendered batches.");
});

test("leaving the library cancels further pages after the first rendered batch", async (t) => {
  const controller = new AbortController();
  let requests = 0;
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    requests++;
    assert.equal(options.signal, controller.signal);
    return Response.json({ products: [{ sku: "6000001" }], has_more: true, next_offset: 1, catalog_snapshot: "first" });
  });
  await assert.rejects(loadProducts(() => controller.abort(), controller.signal), { name: "AbortError" });
  assert.equal(requests, 1);
});

test("invalid cursors stop paging instead of repeatedly requesting the library", async (t) => {
  let requests = 0;
  t.mock.method(globalThis, "fetch", async () => {
    requests++;
    return Response.json({ products: [], has_more: true, next_offset: 0 });
  });
  await assert.rejects(loadProducts(), /invalid page cursor/);
  assert.equal(requests, 1);
});

test("expired accounts still surface the session error before showing protected products", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 401 }));
  await assert.rejects(loadProducts(), SessionExpiredError);
});

test("immutable caching matches built resources but excludes private and unversioned files", () => {
  const config = readFileSync(new URL("../../../ops/frontend-cache.caddy", import.meta.url), "utf8");
  const pattern = config.match(/path_regexp frontend_build (.+)/)[1];
  const matcher = new RegExp(pattern);
  for (const path of ["/assets/index-Cw3m-E_7.js", "/assets/App-BhnhsrNv.js", "/assets/CatalogSheet-B81lGLDZ.css"]) assert.ok(matcher.test(path), path);
  for (const path of ["/", "/index.html", "/assets/kairay-golf-logo.png", "/assets/custom.js", "/thumb/private", "/api/session", "/api/products", "/fonts/NotoSansSC-Regular.ttf"]) assert.equal(matcher.test(path), false, path);
});
