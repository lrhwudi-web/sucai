import assert from "node:assert/strict";
import test from "node:test";
import { normalizeProductTaxonomy } from "../src/utils/category.ts";

test("missing material stays empty instead of showing a placeholder tag", () => {
  assert.equal(
    normalizeProductTaxonomy("Craftsman Golf", "Driver Covers", "").material,
    "",
  );
});

test("No Brand is not reused as material metadata", () => {
  assert.equal(
    normalizeProductTaxonomy("No Brand", "Driver Covers", "No Brand").material,
    "",
  );
});

test("real material metadata remains visible", () => {
  assert.equal(
    normalizeProductTaxonomy("Craftsman Golf", "Driver Covers", "PU Leather").material,
    "PU Leather",
  );
});
