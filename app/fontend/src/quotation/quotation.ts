import type { MaterialProduct } from "../types";

export interface QuoteLine {
  name: string;
  price: string;
  quantity: string;
  note: string;
  brand?: string;
  category?: string;
  priceBulk?: string;
  msrp?: string;
  inventory?: string;
  formula?: string;
  formulaRow?: number;
  formulaRows?: Record<string, string>;
  edited?: string[];
  photoData?: string;
}
export interface PriceRanges { tier1Max: number; tier2Max: number }
export interface SheetLayout { widths: Record<string, number>; heights: Record<string, number>; hidden: string[]; freeze: boolean; labels?: Record<string, string>; priceRanges?: PriceRanges }
export interface QuoteDraft {
  version: 1;
  title: string;
  company: string;
  contact: string;
  reference: string;
  currency: string;
  showBrand: boolean;
  showCategory: boolean;
  showPrice: boolean;
  order: string[];
  lines: Record<string, QuoteLine>;
  layout?: SheetLayout;
}
export const MAX_QUOTE_PRODUCTS = 5000;
export const DEFAULT_PRICE_RANGES: PriceRanges = { tier1Max: 29, tier2Max: 50 };
export const emptyLine = (): QuoteLine => ({ name: "", price: "", quantity: "", note: "" });
export const emptyDraft = (): QuoteDraft => ({ version: 1, title: "Craftsman Golf Accessories Catalog", company: "", contact: "", reference: "", currency: "USD", showBrand: true, showCategory: true, showPrice: true, order: [], lines: {} });
const boundedText = (value: unknown, max: number) => typeof value === "string" ? value.slice(0, max) : "";

export function sanitizeDraft(value: unknown): QuoteDraft {
  const draft = emptyDraft();
  if (!value || typeof value !== "object" || Array.isArray(value)) return draft;
  const source = value as Record<string, unknown>;
  if (source.version !== 1) return draft;
  if (source.layout && typeof source.layout === "object") {
    const layout = source.layout as Record<string, unknown>;
    const sizes = (raw: unknown, min: number, max: number) => Object.fromEntries(Object.entries(raw && typeof raw === "object" ? raw : {}).filter(([k,v]) => !["__proto__","prototype","constructor"].includes(k) && typeof v === "number" && v >= min && v <= max).slice(0,5000));
    const rawLabels=layout.labels&&typeof layout.labels==="object"?layout.labels as Record<string,unknown>:{};
    const labels=Object.fromEntries(["price","priceBulk"].flatMap(key=>typeof rawLabels[key]==="string"&&rawLabels[key].trim()?[[key,boundedText(rawLabels[key],80)]]:[]));
    const rawRanges=layout.priceRanges&&typeof layout.priceRanges==="object"?layout.priceRanges as Record<string,unknown>:{};
    const tier1Max=Number(rawRanges.tier1Max),tier2Max=Number(rawRanges.tier2Max);
    const priceRanges=Number.isInteger(tier1Max)&&Number.isInteger(tier2Max)&&tier1Max>=1&&tier2Max>tier1Max&&tier2Max<=1_000_000?{tier1Max,tier2Max}:undefined;
    draft.layout = { widths: sizes(layout.widths, 55, 600), heights: sizes(layout.heights, 32, 300), hidden: Array.isArray(layout.hidden) ? layout.hidden.filter((v): v is string => typeof v === "string").slice(0,24) : [], freeze: layout.freeze !== false, ...(Object.keys(labels).length?{labels}:{}), ...(priceRanges?{priceRanges}:{}) };
  }
  for (const key of ["title", "company", "contact", "reference"] as const) {
    if (typeof source[key] === "string") draft[key] = boundedText(source[key], 120);
  }
  if (typeof source.currency === "string" && /^[A-Z]{3}$/.test(source.currency)) draft.currency = source.currency;
  for (const key of ["showBrand", "showCategory", "showPrice"] as const) {
    if (typeof source[key] === "boolean") draft[key] = source[key];
  }
  const lines = source.lines && typeof source.lines === "object" ? source.lines as Record<string, unknown> : {};
  draft.order = Array.isArray(source.order)
    ? [...new Set(source.order.filter((sku): sku is string => typeof sku === "string" && sku.length > 0 && sku.length <= 100 && !["__proto__", "constructor", "prototype"].includes(sku)))].slice(0, MAX_QUOTE_PRODUCTS)
    : [];
  // Keep edits on deselected products, so temporarily removing a selection does not erase a quote.
  for (const [sku, raw] of Object.entries(lines).slice(0, 5000)) {
    if (!sku || sku.length > 100 || ["__proto__", "constructor", "prototype"].includes(sku) || !raw || typeof raw !== "object") continue;
    const line = raw as Record<string, unknown>;
    draft.lines[sku] = {
      name: boundedText(line.name, 160),
      price: typeof line.price === "string" && /^\d{0,7}(\.\d{0,2})?$/.test(line.price) ? line.price : "",
      quantity: typeof line.quantity === "string" && /^\d{0,6}$/.test(line.quantity) ? line.quantity : "",
      note: boundedText(line.note, 160),
    };
    const next = draft.lines[sku];
    for (const key of ["brand", "category"] as const) if (typeof line[key] === "string") next[key] = boundedText(line[key], 160);
    for (const key of ["priceBulk", "msrp"] as const) if (typeof line[key] === "string" && /^\d{0,7}(\.\d{0,2})?$/.test(line[key])) next[key] = line[key];
    if (typeof line.inventory === "string" && /^\d{0,8}$/.test(line.inventory)) next.inventory = line.inventory;
    if (typeof line.formula === "string") next.formula = boundedText(line.formula, 5000);
    if (typeof line.formulaRow === "number" && Number.isInteger(line.formulaRow) && line.formulaRow >= 3 && line.formulaRow <= 100000) next.formulaRow = line.formulaRow;
    if (line.formulaRows && typeof line.formulaRows === "object") next.formulaRows = Object.fromEntries(Object.entries(line.formulaRows).filter(([r,sku]) => /^\d{1,6}$/.test(r) && typeof sku === "string" && sku.length <= 100 && !["__proto__","constructor","prototype"].includes(sku)).slice(0,5000)) as Record<string,string>;
    if (Array.isArray(line.edited)) next.edited = line.edited.filter((v): v is string => typeof v === "string" && ["name","brand","category","price","priceBulk","msrp","inventory","quantity","note","formula"].includes(v));
    if (typeof line.photoData === "string" && /^data:image\/(jpeg|png);base64,[A-Za-z0-9+/=]+$/.test(line.photoData) && line.photoData.length < 200000) next.photoData = line.photoData;
  }
  return draft;
}

export function priceRangesOf(draft: QuoteDraft): PriceRanges {
  return draft.layout?.priceRanges || DEFAULT_PRICE_RANGES;
}

export function mergeManagedCatalog(template: QuoteDraft, personal: QuoteDraft): QuoteDraft {
  const manager = sanitizeDraft(template), customer = sanitizeDraft(personal), lines: Record<string, QuoteLine> = { ...manager.lines };
  for (const [sku, line] of Object.entries(customer.lines)) {
    const base = lines[sku] || emptyLine();
    lines[sku] = { ...base, quantity: line.quantity || "", ...(line.formula !== undefined ? { formula: line.formula, formulaRow: line.formulaRow, formulaRows: line.formulaRows } : {}) };
  }
  return { ...manager, company: customer.company, contact: customer.contact, reference: customer.reference, order: customer.order, lines };
}

export function isQuotable(product: MaterialProduct): boolean {
  return !product.otherCategory;
}
export function setQuoteSelection(draft: QuoteDraft, skus: string[], selected: boolean): QuoteDraft {
  const selectedSet = new Set(skus);
  return { ...draft, order: selected ? [...new Set([...draft.order, ...skus])].slice(0, MAX_QUOTE_PRODUCTS) : draft.order.filter((sku) => !selectedSet.has(sku)) };
}
export function moveQuoteLine(draft: QuoteDraft, sku: string, direction: -1 | 1): QuoteDraft {
  const order = [...draft.order];
  const at = order.indexOf(sku); const to = at + direction;
  if (at < 0 || to < 0 || to >= order.length) return draft;
  [order[at], order[to]] = [order[to], order[at]];
  return { ...draft, order };
}
export function priceCents(value: string): number | null {
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(value)) return null;
  const [whole, decimal = ""] = value.split(".");
  return Number(whole) * 100 + Number(decimal.padEnd(2, "0"));
}
export function quantityValue(value: string): number | null {
  return /^\d{1,6}$/.test(value) ? Number(value) : null;
}
export function quoteTotals(draft: QuoteDraft, skus = draft.order) {
  let quantity = 0; let amountCents = 0; let unpriced = 0;
  for (const sku of skus) {
    const line = draft.lines[sku] || emptyLine();
    const qty = quantityValue(line.quantity) ?? 0;
    const price = priceCents(line.price);
    quantity += qty;
    if (qty && price === null) unpriced++;
    else if (price !== null) amountCents += qty * price;
  }
  return { quantity, amountCents, unpriced };
}
export function quoteProducts(draft: QuoteDraft, products: MaterialProduct[]) {
  const available = new Map(products.filter(isQuotable).map((p) => [p.sku, p]));
  return draft.order.flatMap((sku) => { const p = available.get(sku); return p ? [p] : []; });
}
export function formatMoney(cents: number, currency: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(cents / 100);
}
