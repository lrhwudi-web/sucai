import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiEnabled } from "../services/auth.ts";
import { emptyDraft, sanitizeDraft, type QuoteDraft, type QuoteLine } from "./quotation.ts";

export interface CatalogOrderPayload {
  ownerUserId: number | null;
  ownerName: string;
  skuOrder: string[];
  revision: number;
  updatedAt: string | null;
  canManage: boolean;
  draft: QuoteDraft | null;
}

interface RawCatalogOrder {
  owner_user_id: number | null;
  owner_name: string;
  sku_order: string[];
  revision: number;
  updated_at: string | null;
  can_manage: boolean;
  draft: unknown;
}

const EMPTY: CatalogOrderPayload = { ownerUserId: null, ownerName: "", skuOrder: [], revision: 0, updatedAt: null, canManage: false, draft: null };

function normalize(raw: RawCatalogOrder): CatalogOrderPayload {
  return {
    ownerUserId: typeof raw.owner_user_id === "number" ? raw.owner_user_id : null,
    ownerName: typeof raw.owner_name === "string" ? raw.owner_name : "",
    skuOrder: Array.isArray(raw.sku_order) ? [...new Set(raw.sku_order.filter(value => typeof value === "string" && value.length <= 100))].slice(0, 5000) : [],
    revision: Number.isInteger(raw.revision) && raw.revision >= 0 ? raw.revision : 0,
    updatedAt: typeof raw.updated_at === "string" ? raw.updated_at : null,
    canManage: Boolean(raw.can_manage),
    draft: raw.draft && typeof raw.draft === "object" ? sanitizeDraft(raw.draft) : null,
  };
}

async function responseError(response: Response, fallback: string) {
  if (response.headers.get("content-type")?.includes("application/json")) {
    const payload = await response.json() as { detail?: string };
    return payload.detail || fallback;
  }
  return fallback;
}

export function arrangeProducts<T extends { sku: string }>(products: T[], skuOrder: string[]): T[] {
  if (!skuOrder.length) return products;
  const rank = new Map(skuOrder.map((sku, index) => [sku, index]));
  return products.map((product, index) => ({ product, index, rank: rank.get(product.sku) }))
    .sort((a, b) => a.rank === undefined && b.rank === undefined ? a.index - b.index : a.rank === undefined ? 1 : b.rank === undefined ? -1 : a.rank - b.rank)
    .map(item => item.product);
}

export function completeCatalogOrder<T extends { sku: string }>(rows: T[], available: T[]): string[] {
  const ordered = [...new Set(rows.map(product => product.sku))];
  const included = new Set(ordered);
  return [...ordered, ...available.filter(product => !included.has(product.sku)).map(product => product.sku)];
}

export type CatalogGroupKey = "brand" | "category" | "series" | "set" | "sku";

export function groupCatalogProducts<T extends { sku: string; brand?: string; category?: string; themes?: string[]; setCode?: string }>(products: T[], key: CatalogGroupKey, direction: 1 | -1 = 1): T[] {
  const groupValue = (product: T) => {
    if (key === "series") return product.themes?.[0] || "";
    if (key === "set") return product.setCode || "";
    return String(product[key] || "");
  };
  return products.map((product, index) => ({ product, index, value: groupValue(product) })).sort((a, b) => {
    if (!a.value && b.value) return 1;
    if (a.value && !b.value) return -1;
    const grouped = a.value.localeCompare(b.value, undefined, { numeric: true, sensitivity: "base" }) * direction;
    return grouped || a.index - b.index;
  }).map(item => item.product);
}

export function moveCatalogProduct<T extends { sku: string }>(products: T[], sku: string, targetIndex: number): T[] {
  const sourceIndex = products.findIndex(product => product.sku === sku);
  if (sourceIndex < 0 || !products.length) return products;
  const next = [...products];
  const [product] = next.splice(sourceIndex, 1);
  next.splice(Math.max(0, Math.min(next.length, targetIndex)), 0, product);
  return next;
}

export function publishableCatalogDraft(source: QuoteDraft): QuoteDraft {
  const draft = sanitizeDraft(source);
  const lines: Record<string, QuoteLine> = {};
  for (const [sku, line] of Object.entries(draft.lines)) {
    const { quantity: _quantity, formula: _formula, formulaRow: _formulaRow, formulaRows: _formulaRows, photoData: _photoData, ...published } = line;
    lines[sku] = { ...published, quantity: "" };
  }
  return { ...draft, company: "", contact: "", reference: "", order: [], lines };
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, stableValue(item)]));
}

export function catalogDraftFingerprint(source: QuoteDraft | null | undefined): string {
  const draft = publishableCatalogDraft(source || emptyDraft());
  const lines = Object.fromEntries(Object.entries(draft.lines).flatMap(([sku, line]) => {
    const edited = (line.edited || []).filter(key => key !== "quantity" && key !== "formula").sort();
    const hasPublishedValue = [line.name, line.brand, line.category, line.price, line.priceBulk, line.msrp, line.inventory, line.note].some(value => Boolean(value));
    if (!hasPublishedValue && !edited.length) return [];
    return [[sku, { ...line, quantity: "", ...(edited.length ? { edited } : { edited: undefined }) }]];
  }));
  return JSON.stringify(stableValue({ ...draft, lines }));
}

export function useCatalogOrder(accountId: number | null) {
  const [state, setState] = useState<{ accountId: number | null; value: CatalogOrderPayload; loading: boolean; saving: boolean; error: string }>({ accountId: null, value: EMPTY, loading: false, saving: false, error: "" });
  const stateRef = useRef(state);
  const saveQueue = useRef<Promise<unknown>>(Promise.resolve());
  stateRef.current = state;
  useEffect(() => {
    if (accountId === null) { setState({ accountId: null, value: EMPTY, loading: false, saving: false, error: "" }); return; }
    let cancelled = false;
    if (!apiEnabled()) {
      let skuOrder: string[] = [];
      try { skuOrder = JSON.parse(localStorage.getItem(`kairay.catalogOrder.v1:${accountId}`) || "[]"); } catch { /* use default order */ }
      setState({ accountId, value: { ...EMPTY, ownerUserId: accountId, ownerName: "Demo salesperson", skuOrder, canManage: true }, loading: false, saving: false, error: "" });
      return;
    }
    setState({ accountId, value: EMPTY, loading: true, saving: false, error: "" });
    fetch("/api/catalog-order", { credentials: "include", headers: { Accept: "application/json" } })
      .then(async response => { if (!response.ok) throw new Error(await responseError(response, "Customer catalog order could not be loaded.")); return response.json() as Promise<RawCatalogOrder>; })
      .then(payload => { if (!cancelled) setState({ accountId, value: normalize(payload), loading: false, saving: false, error: "" }); })
      .catch(error => { if (!cancelled) setState({ accountId, value: EMPTY, loading: false, saving: false, error: error instanceof Error ? error.message : "Customer catalog order could not be loaded." }); });
    return () => { cancelled = true; };
  }, [accountId]);
  const enqueueSave = useCallback((skuOrder: string[], draft: QuoteDraft | null) => {
    const clean = [...new Set(skuOrder)].slice(0, 5000);
    const execute = async () => {
      const currentState = stateRef.current;
      if (accountId === null || currentState.accountId !== accountId || !currentState.value.canManage) throw new Error("Only administrators can save a customer catalog order.");
      const publishedDraft = draft ? publishableCatalogDraft(draft) : currentState.value.draft || publishableCatalogDraft(emptyDraft());
      stateRef.current = { ...currentState, saving: true, error: "" };
      setState(current => ({ ...current, saving: true, error: "" }));
      try {
        if (!apiEnabled()) {
          localStorage.setItem(`kairay.catalogOrder.v1:${accountId}`, JSON.stringify(clean));
          const value = { ...currentState.value, skuOrder: clean, draft: publishedDraft, revision: currentState.value.revision + 1, updatedAt: new Date().toISOString() };
          stateRef.current = { ...stateRef.current, value, saving: false, error: "" };
          setState(current => ({ ...current, value, saving: false }));
          return value;
        }
        const response = await fetch("/api/catalog-order", { method: "PUT", credentials: "include", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ sku_order: clean, draft: publishedDraft, revision: currentState.value.revision }) });
        if (!response.ok) throw new Error(await responseError(response, "Customer catalog order could not be saved."));
        const value = normalize(await response.json() as RawCatalogOrder);
        stateRef.current = { ...stateRef.current, value, saving: false, error: "" };
        setState(current => ({ ...current, value, saving: false, error: "" }));
        return value;
      } catch (error) {
        const message = error instanceof Error ? error.message : "Customer catalog order could not be saved.";
        stateRef.current = { ...stateRef.current, saving: false, error: message };
        setState(current => ({ ...current, saving: false, error: message }));
        throw new Error(message);
      }
    };
    const queued = saveQueue.current.then(execute, execute);
    saveQueue.current = queued.then(() => undefined, () => undefined);
    return queued;
  }, [accountId]);
  const save = useCallback((skuOrder: string[], draft: QuoteDraft) => enqueueSave(skuOrder, draft), [enqueueSave]);
  const saveOrder = useCallback((skuOrder: string[]) => enqueueSave(skuOrder, null), [enqueueSave]);
  return useMemo(() => ({ ...state.value, loading: state.loading, saving: state.saving, error: state.error, save, saveOrder }), [state, save, saveOrder]);
}
