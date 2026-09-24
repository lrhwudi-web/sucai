import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { MagnifyingGlass, SquaresFour, Table } from "@phosphor-icons/react";
import type { MaterialProduct } from "../types";
import { AssetImage } from "../components/AssetImage";
import { thumbnailVariantUrl } from "../utils/thumbnails";
import { ProductImageGallery } from "./ProductImageGallery";
import { QuoteBuilder } from "./QuoteBuilder";
import { recordCatalogEvent } from "./catalogEvents";
import { inventoryLimit, rawValue, sheetTotals } from "./workbookData";
import { formatMoney, isQuotable, priceCents, priceRangesOf, quantityValue, quoteProducts } from "./quotation";
import type { CatalogSheetProps } from "./WorkbookSheet";
import "./customerCatalog.css";

const PAGE_SIZE = 24;

function stockLabel(product: MaterialProduct, limit: number | null) {
  if (limit === null) return "Stock awaiting confirmation";
  if (limit === 0) return "Currently unavailable";
  if (product.inventoryState === "live" && typeof product.availableInventory === "number") return `${limit.toLocaleString()} available`;
  return `${limit.toLocaleString()} shown · confirm availability`;
}

export function CustomerCatalog({
  products, search, onSearchChange, draft, loading, loadError, onRetry,
  onUpdate, onToggle, onEdit, onNotify, onOpenDrive, onSetCover, onShowWorkbook,
}: CatalogSheetProps & { onShowWorkbook: () => void }) {
  const [mode, setMode] = useState<"browse" | "selected">("browse");
  const [category, setCategory] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [gallery, setGallery] = useState<MaterialProduct | null>(null);
  const deferredSearch = useDeferredValue(search.trim().toLocaleLowerCase());
  const available = useMemo(() => products.filter(isQuotable), [products]);
  const selected = useMemo(() => quoteProducts(draft, products), [draft, products]);
  const selectedSkus = useMemo(() => new Set(selected.map(product => product.sku)), [selected]);
  const categories = useMemo(() => [...new Set(available.map(product => rawValue(draft, product, "category", 3)).filter(Boolean))].sort(), [available, draft]);
  const matching = useMemo(() => {
    const source = mode === "selected" ? selected : available;
    return source.filter(product => {
      const productCategory = rawValue(draft, product, "category", 3);
      if (category && productCategory !== category) return false;
      if (!deferredSearch) return true;
      return [product.sku, rawValue(draft, product, "name", 3), product.chineseName, rawValue(draft, product, "brand", 3), productCategory, product.setCode]
        .some(value => value?.toLocaleLowerCase().includes(deferredSearch));
    });
  }, [available, selected, mode, category, deferredSearch, draft]);
  const shown = matching.slice(0, visibleCount);
  const totals = sheetTotals(draft, selected);
  const updatedAt = available.map(product => product.inventoryUpdatedAt || "").filter(Boolean).sort().at(-1);
  const stockTime = updatedAt && !Number.isNaN(Date.parse(updatedAt))
    ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(updatedAt))
    : "";

  useEffect(() => setVisibleCount(PAGE_SIZE), [mode, category, deferredSearch]);
  useEffect(() => { recordCatalogEvent("catalog_view"); }, []);
  useEffect(() => {
    if (!deferredSearch) return;
    const timer = window.setTimeout(() => recordCatalogEvent("search"), 700);
    return () => window.clearTimeout(timer);
  }, [deferredSearch]);

  const changeQuantity = (product: MaterialProduct, value: string) => {
    if (!/^\d{0,6}$/.test(value)) return;
    const limit = inventoryLimit(draft, product);
    if (value && Number(value) > 0 && (limit === null || Number(value) > limit)) {
      onNotify(limit === null ? `Stock for ${product.sku} needs confirmation.` : `Only ${limit.toLocaleString()} available for ${product.sku}.`);
      return;
    }
    onEdit(product.sku, { quantity: value });
    if (value && Number(value) > 0 && !selectedSkus.has(product.sku)) recordCatalogEvent("product_added", product.sku);
  };

  return <main className="customer-catalog" aria-label="Customer product catalog">
    <header className="customer-catalog-header">
      <div>
        <span className="customer-catalog-eyebrow">YOUR PRODUCT CATALOG</span>
        <h1>{draft.title || "Product catalog"}</h1>
        <p>Browse products, enter quantities and send your order to your salesperson.</p>
      </div>
      <button type="button" className="customer-catalog-workbook" onClick={onShowWorkbook}><Table size={18} /> Workbook view</button>
    </header>

    <section className="customer-catalog-controls" aria-label="Find products">
      <label className="customer-catalog-search"><MagnifyingGlass size={20} aria-hidden="true" /><span className="sr-only">Search products by name or SKU</span>
        <input value={search} onChange={event => onSearchChange(event.target.value)} placeholder="Search products or SKU" autoComplete="off" />
      </label>
      <label className="customer-catalog-category"><span className="sr-only">Category</span><select value={category} onChange={event => setCategory(event.target.value)}><option value="">All categories</option>{categories.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
      <div className="customer-catalog-tabs" role="tablist" aria-label="Catalog products">
        <button type="button" role="tab" aria-selected={mode === "browse"} onClick={() => setMode("browse")}>Browse</button>
        <button type="button" role="tab" aria-selected={mode === "selected"} onClick={() => setMode("selected")}>My order <span>{selected.length}</span></button>
      </div>
    </section>

    <div className="customer-catalog-meta"><span>{matching.length.toLocaleString()} products{category ? ` · ${category}` : ""}</span>{stockTime && <span>Inventory updated {stockTime}</span>}</div>
    {loadError ? <div className="customer-catalog-state" role="alert">{loadError}<button type="button" onClick={onRetry}>Try again</button></div>
      : loading && !available.length ? <div className="customer-catalog-state" role="status">Loading products…</div>
      : matching.length === 0 ? <div className="customer-catalog-state"><SquaresFour size={30} /><strong>{mode === "selected" ? "Your order is empty" : "No products found"}</strong><span>{mode === "selected" ? "Add products from Browse to start an order." : "Try a different SKU, name or category."}</span>{mode === "selected" && <button type="button" onClick={() => setMode("browse")}>Browse products</button>}</div>
      : <>
        <div className="customer-catalog-grid">
          {shown.map(product => {
            const line = draft.lines[product.sku];
            const limit = inventoryLimit(draft, product);
            const quantity = line?.quantity || "";
            const isSelected = selectedSkus.has(product.sku);
            const ranges = priceRangesOf(draft);
            const tier1 = priceCents(line?.price || "");
            const tier2 = priceCents(line?.priceBulk || "");
            const qty = quantityValue(quantity) || 0;
            const effectivePrice = qty > ranges.tier2Max ? null : qty > ranges.tier1Max ? tier2 : tier1;
            const photo = rawValue(draft, product, "photo", 3);
            return <article className={`customer-product-card${isSelected ? " is-selected" : ""}`} key={product.sku}>
              <button type="button" className="customer-product-image" onClick={() => { recordCatalogEvent("product_open", product.sku); setGallery(product); }} aria-label={`View photos for ${product.name}`}>
                <AssetImage src={photo.startsWith("data:") ? photo : thumbnailVariantUrl(photo, "small")} alt={product.name} loading="lazy" />
              </button>
              <div className="customer-product-copy">
                <span className="customer-product-brand">{rawValue(draft, product, "brand", 3) || "Product"}{rawValue(draft, product, "category", 3) ? ` · ${rawValue(draft, product, "category", 3)}` : ""}</span>
                <h2>{rawValue(draft, product, "name", 3) || product.name}</h2>
                <span className="customer-product-sku">SKU {product.sku}</span>
                <div className="customer-product-prices">
                  <strong>{tier1 !== null ? formatMoney(tier1, draft.currency) : "Ask for price"}</strong>
                  <span>{tier2 !== null ? `${ranges.tier1Max + 1}–${ranges.tier2Max} pcs: ${formatMoney(tier2, draft.currency)}` : ""}</span>
                </div>
                <span className={`customer-product-stock${limit === null || limit === 0 ? " is-unavailable" : ""}`}>{stockLabel(product, limit)}</span>
                {isSelected ? <div className="customer-product-quantity"><label>Qty<input type="number" inputMode="numeric" min="1" max={Math.min(limit ?? 999999, 999999)} value={quantity} onChange={event => changeQuantity(product, event.target.value)} aria-label={`Quantity for ${product.sku}`} /></label><button type="button" onClick={() => { onToggle([product.sku], false); recordCatalogEvent("product_removed", product.sku); }}>Remove</button></div>
                  : <button type="button" className="customer-product-add" disabled={limit === null || limit < 1} onClick={() => changeQuantity(product, "1")}>Add to order</button>}
                {isSelected && qty > 0 && <span className="customer-product-subtotal">{effectivePrice === null ? "Price to be confirmed" : `Est. ${formatMoney(effectivePrice * qty, draft.currency)}`}</span>}
              </div>
            </article>;
          })}
        </div>
        {matching.length > visibleCount && <button type="button" className="customer-catalog-more" onClick={() => setVisibleCount(count => count + PAGE_SIZE)}>Show more products ({(matching.length - visibleCount).toLocaleString()} remaining)</button>}
      </>}

    <div className="customer-catalog-order-bar" aria-label="Order summary"><div><strong>{selected.length} products · {totals.quantity.toLocaleString()} pcs</strong><span>{totals.unpriced ? "Priced subtotal" : "Estimated total"}: {formatMoney(totals.amountCents, draft.currency)}{totals.unpriced ? ` · ${totals.unpriced} prices pending` : ""}</span></div><QuoteBuilder draft={draft} products={products} displayedProducts={selected} canManageCatalogOrder={false} onUpdate={onUpdate} onNotify={onNotify} /></div>
    {gallery && <ProductImageGallery product={gallery} importedPhoto={draft.lines[gallery.sku]?.photoData || ""} onOpenDrive={() => onOpenDrive(gallery)} canSetCover={false} onSetCover={onSetCover} onNotify={onNotify} onClose={() => setGallery(null)} />}
  </main>;
}
