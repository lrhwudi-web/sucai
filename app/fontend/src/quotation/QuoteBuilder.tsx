import { useEffect, useRef, useState } from "react";
import { ArrowCounterClockwise, CheckCircle, FileXls, SpinnerGap, X } from "@phosphor-icons/react";
import type { MaterialProduct } from "../types";
import { AssetImage } from "../components/AssetImage";
import { submitCustomerOrder, type CustomerOrder } from "../orders/orderService";
import { columnLabel, columnsForCatalog, createCalculator, inventoryLimit, layoutOf, rawValue, sheetTotals } from "./workbookData";
import { formatMoney, isQuotable, moveQuoteLine, priceCents, priceRangesOf, quantityValue, quoteProducts, type QuoteDraft } from "./quotation";

interface Props {
  draft: QuoteDraft;
  products: MaterialProduct[];
  displayedProducts: MaterialProduct[];
  canManageCatalogOrder: boolean;
  onUpdate: (fn: (draft: QuoteDraft) => QuoteDraft) => void;
  onNotify: (message: string) => void;
}

export function QuoteBuilder({ draft, products, displayedProducts, canManageCatalogOrder, onUpdate, onNotify }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const successNotice = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<"selected" | "sheet">("sheet");
  const [exporting, setExporting] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [readyExcel, setReadyExcel] = useState<{ url: string; name: string; size: number } | null>(null);
  const [readyOrder, setReadyOrder] = useState<CustomerOrder | null>(null);
  const orderAttempt = useRef("");
  const selected = quoteProducts(draft, products);
  const eligible = displayedProducts.filter(isQuotable);
  const exportProducts = canManageCatalogOrder && scope === "sheet" ? eligible : selected;
  const totals = sheetTotals(draft, exportProducts);
  const sheetColumns = columnsForCatalog(canManageCatalogOrder);
  const calc = createCalculator(draft, exportProducts, sheetColumns);
  const layout = layoutOf(draft);
  const priceRanges = priceRangesOf(draft);
  const columns = sheetColumns.filter(c => !layout.hidden.includes(c.key));
  const salesWarehouseName = exportProducts.find(product => product.salesWarehouseName)?.salesWarehouseName || "";
  const missing = draft.order.length - selected.length;

  useEffect(() => () => { if (readyExcel) URL.revokeObjectURL(readyExcel.url); }, [readyExcel]);
  useEffect(() => { setReadyExcel(null); setReadyOrder(null); orderAttempt.current = ""; }, [draft, scope]);
  useEffect(() => { if (readyOrder) successNotice.current?.focus(); }, [readyOrder]);
  useEffect(() => {
    const el = dialog.current;
    if (open && !el?.open) el?.showModal();
    else if (!open && el?.open) el.close();
  }, [open]);

  const set = (patch: Partial<QuoteDraft>) => onUpdate(d => ({ ...d, ...patch }));
  const exportExcel = async () => {
    setError("");
    if (!draft.title.trim()) { setError("Enter a catalog title before exporting."); return; }
    if (exportProducts.some(p => ["price", "priceBulk"].some(key => {
      const value = draft.lines[p.sku]?.[key as "price" | "priceBulk"];
      return value && priceCents(value) === null;
    }))) { setError("Complete the unit prices, or leave them blank to request a quote."); return; }
    setExporting(true);
    setProgress("Preparing your Excel catalog…");
    try {
      const { downloadCatalogExcel } = await import("./exportCatalog");
      const result = await downloadCatalogExcel(draft, exportProducts, setProgress, sheetColumns);
      setReadyExcel(result);
      onNotify(result.missingImages ? `Excel ready. ${result.missingImages} product photos were unavailable.` : "Excel ready with product pictures and amount formulas.");
    } catch (e) { setError(e instanceof Error ? e.message : "The catalog could not be exported. Please try again."); }
    finally { setExporting(false); setProgress(""); }
  };

  const placeOrder = async () => {
    setError("");
    if (!draft.title.trim()) { setError("Enter an order title before placing the order."); return; }
    if (!exportProducts.length) { setError("Select at least one product before placing an order."); return; }
    if (exportProducts.some(product => (quantityValue(draft.lines[product.sku]?.quantity || "") || 0) <= 0)) {
      setError("Enter a quantity greater than zero for every selected product."); return;
    }
    const overInventory = exportProducts.find(product => {
      const quantity = quantityValue(draft.lines[product.sku]?.quantity || "") || 0;
      const limit = inventoryLimit(draft, product);
      return limit === null || quantity > limit;
    });
    if (overInventory) {
      const limit = inventoryLimit(draft, overInventory);
      setError(limit === null ? `Inventory is unavailable for SKU ${overInventory.sku}. Refresh the catalog and try again.` : `SKU ${overInventory.sku}: order quantity cannot exceed inventory (${limit.toLocaleString()}).`); return;
    }
    if (exportProducts.some(p => ["price", "priceBulk"].some(key => {
      const value = draft.lines[p.sku]?.[key as "price" | "priceBulk"];
      return value && priceCents(value) === null;
    }))) { setError("Complete the unit prices, or leave them blank to request a quote."); return; }
    if (!window.confirm(`Place this order for ${totals.quantity.toLocaleString()} pieces across ${exportProducts.length} products?`)) return;
    setExporting(true);
    setProgress("Preparing the order Excel…");
    try {
      const { createCatalogExcel } = await import("./exportCatalog");
      const excel = await createCatalogExcel(draft, exportProducts, setProgress, sheetColumns, { centerNote: true });
      if (!orderAttempt.current) orderAttempt.current = crypto.randomUUID().replaceAll("-", "");
      setProgress("Submitting order…");
      const orderItems = exportProducts.map((product, row) => {
        const quantity = quantityValue(draft.lines[product.sku]?.quantity || "") || 0;
        const price = quantity <= priceRanges.tier1Max
          ? priceCents(draft.lines[product.sku]?.price || "")
          : quantity <= priceRanges.tier2Max ? priceCents(draft.lines[product.sku]?.priceBulk || "") : null;
        const amount = calc.cell(row, "amount");
        const image = product.assets.find((asset) => asset.kind === "image" && !asset.internalOnly && asset.thumbnailUrl.startsWith("/thumb/"));
        return {
          sku: product.sku,
          name: String(rawValue(draft, product, "name", row + 3)),
          quantity,
          unitPriceCents: price,
          amountCents: typeof amount === "number" ? Math.round(amount * 100) : null,
          imageUrl: image?.thumbnailUrl || "",
        };
      });
      const result = await submitCustomerOrder({
        idempotencyKey: orderAttempt.current,
        excel: excel.blob,
        excelName: excel.name,
        title: draft.title,
        company: draft.company,
        contact: draft.contact,
        reference: draft.reference,
        currency: draft.currency,
        productCount: exportProducts.length,
        totalQuantity: totals.quantity,
        totalAmountCents: totals.amountCents,
        unpricedCount: totals.unpriced,
        items: orderItems,
      });
      setReadyOrder(result.order);
      try {
        sessionStorage.setItem("kairay.orderSuccess", JSON.stringify({
          orderNumber: result.order.orderNumber,
          salespersonName: result.order.salespersonName,
          notificationStatus: result.order.notificationStatus,
        }));
      } catch { /* The order remains saved when browser storage is unavailable. */ }
      orderAttempt.current = "";
      onNotify(result.notificationWarning || (excel.missingImages ? `Order placed. ${excel.missingImages} product photos were unavailable.` : "Order placed and your salesperson was notified."));
    } catch (e) { setError(e instanceof Error ? e.message : "The order could not be submitted. Please try again."); }
    finally { setExporting(false); setProgress(""); }
  };

  return <>
    <button className="quote-button is-primary" disabled={canManageCatalogOrder ? !selected.length && !eligible.length : !selected.length}
      onClick={() => { setError(""); setScope(selected.length ? "selected" : "sheet"); setOpen(true); }}>
      <FileXls size={18} />{canManageCatalogOrder ? "Export Excel" : "Place order"}{selected.length > 0 && <span>{selected.length}</span>}
    </button>
    <dialog ref={dialog} className="quote-dialog" aria-labelledby="quote-dialog-title"
      onCancel={e => { if (exporting) e.preventDefault(); else setOpen(false); }} onClose={() => setOpen(false)}>
      <div className="quote-dialog-content">
        <header className="quote-dialog-header">
          <div><span className="quote-eyebrow">{canManageCatalogOrder ? "YOUR CUSTOMER CATALOG" : "CONFIRM CUSTOMER ORDER"}</span><h2 id="quote-dialog-title">{canManageCatalogOrder ? "Export Excel catalog" : "Place order"}</h2>
            <p>{canManageCatalogOrder?"Review the administrator catalog columns before exporting.":"Review the products and quantities below. After confirmation, the order is saved and your salesperson receives the Excel download link."}</p></div>
          <button className="quote-icon-button" aria-label="Close Excel export" disabled={exporting} onClick={() => setOpen(false)}><X size={22} /></button>
        </header>
        {readyOrder && <div ref={successNotice} className="quote-order-success" role="status" aria-live="polite" tabIndex={-1}>
          <CheckCircle size={28} weight="fill" aria-hidden="true" />
          <div><strong>Order submitted successfully</strong><span>Order {readyOrder.orderNumber} · {readyOrder.fileName}</span></div>
          <a href={readyOrder.downloadUrl}><FileXls size={18} aria-hidden="true" />Download order Excel</a>
        </div>}
        <fieldset disabled={exporting} className="quote-details-grid"><legend className="quote-sr-only">Excel export details</legend>
          <label className="quote-title-field">{canManageCatalogOrder ? "Catalog title" : "Order title"}<input value={draft.title} maxLength={120} onChange={e => set({ title: e.target.value })} /></label>
          {canManageCatalogOrder ? <label>Products to export<select value={scope} onChange={e => setScope(e.target.value as "selected" | "sheet")}>
            <option value="selected" disabled={!selected.length}>Selected products ({selected.length})</option>
            <option value="sheet">Current worksheet ({eligible.length})</option>
          </select></label> : <label>Order products<input value={`${selected.length} selected products`} readOnly /></label>}
          <label>Your company<input value={draft.company} placeholder="Company name" maxLength={120} onChange={e => set({ company: e.target.value })} /></label>
          <label>Reply-to contact<input value={draft.contact} placeholder="Email or phone" maxLength={120} onChange={e => set({ contact: e.target.value })} /></label>
          <label>Quote reference<input value={draft.reference} placeholder="Optional" maxLength={120} onChange={e => set({ reference: e.target.value })} /></label>
          <label>Currency<select value={draft.currency} onChange={e => set({ currency: e.target.value })}>{["USD", "EUR", "GBP", "CAD", "AUD", "CNY", "JPY"].map(currency => <option key={currency}>{currency}</option>)}</select></label>
        </fieldset>
        <div className="quote-column-options"><strong>Visible columns</strong>{sheetColumns.map(c => <label key={c.key}>
          <input type="checkbox" checked={!layout.hidden.includes(c.key)} disabled={exporting}
            onChange={e => {
              if (!e.target.checked && columns.length === 1) { onNotify("Keep at least one column visible."); return; }
              set({ layout: { ...layout, hidden: e.target.checked ? layout.hidden.filter(k => k !== c.key) : [...layout.hidden, c.key] } });
            }} />{columnLabel(c, salesWarehouseName, layout.labels, layout.priceRanges).replace("\n", " ")}</label>)}<span>Hidden columns can be shown again in Excel.</span></div>
        {scope === "selected" && missing > 0 && <p className="quote-warning" role="status">{missing} previously selected products are no longer available to this account and will be excluded.</p>}
        <div className="quote-editor-area wb-export-preview" inert={exporting || undefined}>
          {exportProducts.length ? <table><thead><tr>{scope === "selected" && <th>ORDER</th>}{columns.map(c => <th key={c.key}>{columnLabel(c, salesWarehouseName, layout.labels, layout.priceRanges)}</th>)}</tr></thead>
            <tbody>{exportProducts.map((p, row) => <tr key={p.sku}>
              {scope === "selected" && <td><button aria-label={`Move ${p.sku} up`} disabled={!row} onClick={() => onUpdate(d => moveQuoteLine(d, p.sku, -1))}>↑</button>
                <button aria-label={`Move ${p.sku} down`} disabled={row === selected.length - 1} onClick={() => onUpdate(d => moveQuoteLine(d, p.sku, 1))}>↓</button></td>}
              {columns.map(c => { const value = calc.cell(row, c.key); return <td key={c.key}>{c.key === "photo"
                ? <AssetImage src={rawValue(draft, p, "photo", row + 3)} alt={p.name} loading="lazy" />
                : typeof value === "number" && ["price", "priceBulk", "msrp", "amount"].includes(c.key) ? formatMoney(Math.round(value * 100), draft.currency) : String(value)}</td>; })}
            </tr>)}</tbody></table> : <div className="quote-empty">No products to export. Choose the current worksheet or select products in the catalog.</div>}
        </div>
        <footer className="quote-dialog-footer">
          <div className="quote-totals"><strong>{exportProducts.length} products{!canManageCatalogOrder&&<> <span>·</span> {totals.quantity.toLocaleString()} pcs</>}</strong>
            {!canManageCatalogOrder&&<span>{totals.unpriced ? "Priced subtotal" : "Subtotal"}: <b>{formatMoney(totals.amountCents, draft.currency)}</b>{totals.unpriced > 0 && ` · ${totals.unpriced} awaiting price`}</span>}</div>
          {selected.length > 0 && <button className="quote-button" disabled={exporting} onClick={() => { onUpdate(d => ({ ...d, order: [] })); setScope("sheet"); }}><ArrowCounterClockwise size={16} />Clear selection</button>}
          <button className="quote-button is-primary" disabled={!exportProducts.length || exporting} onClick={canManageCatalogOrder ? exportExcel : placeOrder}>
            {exporting ? <SpinnerGap className="is-spinning" size={18} /> : <FileXls size={18} />}{exporting ? progress : canManageCatalogOrder ? "Download Excel" : "Confirm order"}
          </button>
        </footer>
        {readyExcel && <div className="wb-download"><span>Excel ready · {Math.ceil(readyExcel.size / 1024)} KB</span><a href={readyExcel.url} download={readyExcel.name}>Save Excel file</a></div>}
        {error && <p className="quote-error" role="alert">{error}</p>}
      </div>
    </dialog>
  </>;
}
