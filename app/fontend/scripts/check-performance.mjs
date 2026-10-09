import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

const dist = new URL("../dist/", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL(".vite/manifest.json", dist), "utf8"));
const entry = Object.keys(manifest).find((key) => manifest[key].isEntry);
assert.ok(entry, "Build the frontend before checking its initial resources.");
const visited = new Set();
const files = new Set();
function collect(key) {
  if (visited.has(key)) return;
  visited.add(key);
  const chunk = manifest[key];
  files.add(chunk.file);
  for (const css of chunk.css || []) files.add(css);
  for (const dependency of chunk.imports || []) collect(dependency);
}
collect(entry);
let javascript = 0;
let styles = 0;
for (const file of files) {
  const bytes = readFileSync(new URL(file, dist));
  const compressed = gzipSync(bytes).length;
  if (file.endsWith(".js")) javascript += compressed;
  if (file.endsWith(".css")) styles += compressed;
  console.log(`${file}: ${(bytes.length / 1000).toFixed(1)} KB, gzip ${(compressed / 1000).toFixed(1)} KB`);
}
assert.ok(javascript < 100_000, `Initial JavaScript exceeds the 100 KB gzip budget: ${javascript}`);
assert.ok(styles < 45_000, `Initial CSS exceeds the 45 KB gzip budget: ${styles}`);
const workspace = Object.keys(manifest).find((key) => manifest[key].name === "App");
assert.ok(workspace && !visited.has(workspace), "The authenticated workspace must stay out of the public entry graph.");
assert.ok(manifest[workspace]?.isDynamicEntry, "The workspace must be loaded on demand.");
for (const name of ["AdminPanel", "SuperAdminPanel", "OrdersPanel", "CatalogSheet"]) {
  assert.ok(Object.values(manifest).some((chunk) => chunk.isDynamicEntry && chunk.name === name), `${name} must remain a separate page chunk.`);
}
console.log(`Initial total: ${((javascript + styles) / 1000).toFixed(1)} KB gzip. Resource budgets passed.`);
