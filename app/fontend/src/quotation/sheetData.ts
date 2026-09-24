import type { QuoteLine } from "./quotation";

export type SheetColumn = "photo" | "sku" | "name" | "brand" | "category" | "price" | "quantity" | "amount" | "note";
export const EDITABLE_COLUMNS = new Set<SheetColumn>(["name", "price", "quantity", "note"]);

export function normalizeSheetValue(column: SheetColumn, value: string): string | null {
  const text = value.replace(/[\r\n\t]+/g, " ");
  if (column === "price") {
    const price = text.trim().replace(/,/g, "");
    return /^\d{0,7}(\.\d{0,2})?$/.test(price) ? price.replace(/\.$/, "") : null;
  }
  if (column === "quantity") return /^\d{0,6}$/.test(text.trim()) ? text.trim() : null;
  return text.slice(0, 160);
}

/** Map TSV by the visible columns, retaining read-only gaps and row order. */
export function parseSheetPaste(text: string, skus: string[], columns: SheetColumn[], row: number, col: number) {
  const patches: { sku: string; patch: Partial<QuoteLine> }[] = [];
  let invalid = 0, clipped = 0;
  const matrix = text.replace(/\r\n?/g, "\n").replace(/\n$/, "").split("\n");
  matrix.forEach((line, r) => {
    const sku = skus[row + r];
    if (!sku) { clipped++; return; }
    const patch: Partial<QuoteLine> = {};
    line.split("\t").forEach((value, c) => {
      const column = columns[col + c];
      if (!column) { clipped++; return; }
      if (!EDITABLE_COLUMNS.has(column)) return;
      const normalized = normalizeSheetValue(column, value);
      if (normalized === null) invalid++;
      else patch[column as "name" | "price" | "quantity" | "note"] = normalized;
    });
    if (Object.keys(patch).length) patches.push({ sku, patch });
  });
  return { patches, invalid, clipped };
}
