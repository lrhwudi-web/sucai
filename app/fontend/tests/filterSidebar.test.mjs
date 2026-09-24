import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sidebar = fs.readFileSync(path.join(root, "src", "components", "FilterSidebar.tsx"), "utf8");
const styles = fs.readFileSync(path.join(root, "src", "styles.css"), "utf8");
const app = fs.readFileSync(path.join(root, "src", "App.tsx"), "utf8");

test("Craftsman Golf is prioritized in the brand filter", () => {
  assert.match(sidebar, /const prioritizeBrandOptions/);
  assert.match(sidebar, /aIsCraftsmanGolf \? -1 : 1/);
  assert.match(sidebar, /options=\{prioritizeBrandOptions\(/);
});

test("brand and product-category options use readable type", () => {
  assert.match(styles, /\.filter-choice \{[\s\S]*?font-size: 12px;/);
  assert.match(styles, /\.category-filter-heading \{[\s\S]*?font-size: 12px;/);
  assert.match(styles, /\.category-check \{[\s\S]*?font-size: 12px;/);
});

test("theme and other-collection controls use readable type", () => {
  assert.match(styles, /\.theme-chip \{[\s\S]*?font-size: 12px;/);
  assert.match(styles, /\.other-collections > p \{[\s\S]*?font-size: 11px;/);
  assert.match(styles, /\.other-collection-row \{[\s\S]*?font-size: 12px;/);
});

test("asset-type controls use readable type and icons", () => {
  assert.match(sidebar, /<Icon size=\{18\} weight=\{selected/);
  assert.match(styles, /\.asset-type-segments button \{[\s\S]*?min-height: 34px;[\s\S]*?font-size: 12px;/);
});

test("selecting an other collection resets product filters", () => {
  assert.match(sidebar, /Clicking a collection resets the product filters above/);
  assert.match(app, /if \(key === "other"\)/);
  assert.match(app, /\{ \.\.\.emptyFilters, other: nextOther \}/);
  assert.match(app, /assetKind: "", other: \[\]/);
});
