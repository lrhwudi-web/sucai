import assert from "node:assert/strict";
import test from "node:test";
import {
  normalizePastedSearchText,
  parseCatalogueSearch,
} from "../src/utils/catalogueSearch.ts";

const pastedSkus = `7203235
7202685
6012870
7203234
6012648
7200268
6009062
6012518
6000755
6008815
6009239
7203236
6009099
7200268
7202685
6000240
6000240
7203236
7202685
6011651
7203236`;

test("parses a pasted SKU list and removes duplicates without changing order", () => {
  const parsed = parseCatalogueSearch(pastedSkus);

  assert.equal(parsed.isBatchSkuSearch, true);
  assert.deepEqual(parsed.skuOrder, [
    "7203235", "7202685", "6012870", "7203234", "6012648",
    "7200268", "6009062", "6012518", "6000755", "6008815",
    "6009239", "7203236", "6009099", "6000240", "6011651",
  ]);
  assert.equal(parsed.skuSet.size, 15);
});

test("accepts spaces and Chinese or English punctuation between SKUs", () => {
  const parsed = parseCatalogueSearch("7203235, 7202685；6012870，7203234");

  assert.equal(parsed.isBatchSkuSearch, true);
  assert.deepEqual(parsed.skuOrder, ["7203235", "7202685", "6012870", "7203234"]);
});

test("keeps normal keyword searches and single SKU searches unchanged", () => {
  assert.equal(parseCatalogueSearch("event sponsorships").isBatchSkuSearch, false);
  assert.equal(parseCatalogueSearch("7203235").isBatchSkuSearch, false);
});

test("normalizes line breaks before inserting pasted text into the single-line input", () => {
  assert.equal(normalizePastedSearchText("7203235\r\n7202685\n6012870"), "7203235 7202685 6012870");
});
