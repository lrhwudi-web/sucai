import assert from "node:assert/strict";
import test from "node:test";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { PDFDocument } from "pdf-lib";
import { emptyDraft, sanitizeDraft, setQuoteSelection, moveQuoteLine, quoteProducts, quoteTotals, priceCents, MAX_QUOTE_PRODUCTS } from "../src/quotation/quotation.ts";
import { createQuotationPdf } from "../src/quotation/quotationPdf.ts";

const product = (sku, otherCategory = "") => ({ sku, name: "Golf cover " + sku, brand: "Craftsman Golf", category: "Driver Covers", otherCategory, material: "", batch: "", permission: "public", owner: "", updatedAt: "2026-09-04", drivePath: "DO NOT EXPORT / internal source path", themes: [], assets: [] });

test("selection survives filters, page changes and removal without losing edited values", () => {
  let draft = setQuoteSelection(emptyDraft(), ["001", "002"], true);
  draft.lines["001"] = { name: "Custom item", price: "12.50", quantity: "20", note: "Blue" };
  assert.deepEqual(quoteProducts(draft, [product("002"), product("001")]).map(p => p.sku), ["001", "002"]);
  draft = setQuoteSelection(draft, ["001"], false);
  draft = setQuoteSelection(draft, ["001"], true);
  assert.equal(draft.lines["001"].price, "12.50");
  assert.deepEqual(draft.order, ["002", "001"]);
  assert.deepEqual(moveQuoteLine(draft, "001", -1).order, ["001", "002"]);
});
test("unavailable SKUs and non-product collections never enter export", () => {
  const draft = setQuoteSelection(emptyDraft(), ["001", "private", "document"], true);
  assert.deepEqual(quoteProducts(draft, [product("001"), product("document", "Product Catalogs")]).map(p => p.sku), ["001"]);
});
test("money is exact in cents and unknown prices remain unknown", () => {
  const draft = setQuoteSelection(emptyDraft(), ["a", "b", "c"], true);
  draft.lines = { a: { price: "0.10", quantity: "3" }, b: { price: "", quantity: "9" }, c: { price: "0", quantity: "2" } };
  assert.deepEqual(quoteTotals(draft), { quantity: 14, amountCents: 30, unpriced: 1 });
  for (const bad of ["-1", "NaN", "Infinity", "1.001", "1e4", "1.", "."]) assert.equal(priceCents(bad), null);
});
test("corrupt and oversized saved drafts are bounded and prototype keys are rejected", () => {
  assert.deepEqual(sanitizeDraft({ version: 0 }), emptyDraft());
  const draft = sanitizeDraft(JSON.parse('{"version":1,"currency":"invalid","order":["__proto__","001","001"],"lines":{"__proto__":{"name":"bad"},"001":{"quantity":"-1","price":"Infinity","name":"OK"}}}'));
  assert.deepEqual(draft.order, ["001"]);
  assert.equal(draft.currency, "USD");
  assert.equal(draft.lines["001"].quantity, "");
  assert.equal(draft.lines["001"].price, "");
  assert.equal(Object.hasOwn(draft.lines, "__proto__"), false);
  assert.equal(sanitizeDraft({ version: 1, order: Array.from({ length: MAX_QUOTE_PRODUCTS + 999 }, (_, i) => String(i)) }).order.length, MAX_QUOTE_PRODUCTS);
});
test("multi-page PDF preserves editable values and output order", async () => {
  const products = Array.from({ length: 15 }, (_, i) => product(`SKU-${i}`));
  const draft = emptyDraft(); draft.company = "Example Golf Supply"; draft.order = products.map(p => p.sku);
  draft.lines["SKU-0"] = { name: "A custom product name", price: "12.50", quantity: "25", note: "Blue, please" };
  const bytes = await createQuotationPdf(draft, products, { images: new Map() });
  const pdf = await PDFDocument.load(bytes);
  assert.ok(pdf.getPageCount() >= 3);
  assert.equal(pdf.getForm().getTextField("item_0_quantity").getText(), "25");
  assert.equal(pdf.getForm().getTextField("item_0_price").getText(), "12.50");
  assert.equal(pdf.getForm().getTextField("item_0_note").getText(), "Blue, please");
  assert.equal(pdf.getForm().getFields().length, 15 * 4 + 2);
  pdf.getForm().getTextField("item_0_quantity").setText("120");
  const reopened = await PDFDocument.load(await pdf.save());
  assert.equal(reopened.getForm().getTextField("item_0_quantity").getText(), "120");
  await mkdir("tests/output", { recursive: true }); await writeFile("tests/output/quotation.pdf", bytes);
});
test("hidden unit prices are absent from the PDF field tree", async () => {
  const draft = emptyDraft(); draft.showPrice = false; draft.showBrand = false; draft.showCategory = false;
  const pdf = await PDFDocument.load(await createQuotationPdf(draft, [product("001")], { images: new Map() }));
  assert.ok(!pdf.getForm().getFields().some(f => f.getName().includes("price")));
  assert.equal(pdf.getForm().getFields().length, 4);
});
test("Chinese company names and notes retain an editable CJK font", async () => {
  const draft = emptyDraft(); draft.company = "凯锐高尔夫";
  draft.lines["001"] = { name: "定制球杆套", price: "18.50", quantity: "100", note: "蓝色，单独包装" };
  const fontBytes = new Uint8Array(await readFile("public/fonts/NotoSansSC-Regular.ttf"));
  const bytes = await createQuotationPdf(draft, [product("001")], { images: new Map(), fontBytes });
  const pdf = await PDFDocument.load(bytes);
  assert.equal(pdf.getForm().getTextField("item_0_note").getText(), "蓝色，单独包装");
  assert.ok(bytes.length < 7_000_000, `CJK PDF unexpectedly large: ${bytes.length}`);
  await mkdir("tests/output", { recursive: true }); await writeFile("tests/output/quotation-unicode.pdf", bytes);
});
