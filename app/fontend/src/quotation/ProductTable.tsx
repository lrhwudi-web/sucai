import { ArrowSquareOut, Heart, FilePdf, ArrowUp, ArrowDown, X } from "@phosphor-icons/react";
import { useEffect, useRef } from "react";
import type { MaterialProduct } from "../types";
import { AssetImage } from "../components/AssetImage";
import { thumbnailVariantUrl } from "../utils/thumbnails";
import { emptyLine, formatMoney, isQuotable, priceCents, quantityValue, type QuoteDraft, type QuoteLine } from "./quotation";

export interface ProductTableProps {
  products: MaterialProduct[];
  draft: QuoteDraft;
  onToggle: (skus: string[], selected: boolean) => void;
  onEdit: (sku: string, patch: Partial<QuoteLine>) => void;
  onSelect: (sku: string) => void;
  onFavorite?: (product: MaterialProduct) => void;
  onOpenDrive?: (product: MaterialProduct) => void;
  onMove?: (sku: string, direction: -1 | 1) => void;
  editor?: boolean;
}
export function ProductTable({ products, draft, onToggle, onEdit, onSelect, onFavorite, onOpenDrive, onMove, editor = false }: ProductTableProps) {
  const ImageTag = editor ? "div" : "button";
  const SkuTag = editor ? "span" : "button";
  const checkbox = useRef<HTMLInputElement>(null);
  const eligible = products.filter(isQuotable).map((p) => p.sku);
  const selected = new Set(draft.order);
  const checked = eligible.length > 0 && eligible.every((sku) => selected.has(sku));
  useEffect(() => { if (checkbox.current) checkbox.current.indeterminate = !checked && eligible.some((sku) => selected.has(sku)); }, [checked, eligible, selected]);
  return <div className="quote-table-scroll" role="region" aria-label={editor ? "Selected products quotation" : "Products table"} tabIndex={0}>
    <table className={`quote-table ${editor ? "is-editor" : ""}`}>
      <thead><tr>
        <th className="quote-check-col">{editor ? "Order" : <input ref={checkbox} type="checkbox" aria-label="Select all products on this page" checked={checked} disabled={!eligible.length} onChange={(e) => onToggle(eligible, e.target.checked)} />}</th>
        <th>Product</th>
        {draft.showPrice && <th>Unit price <small>{draft.currency}</small></th>}
        <th>Qty <small>pcs</small></th>
        {draft.showBrand && <th>Brand</th>}
        {draft.showCategory && <th>Category</th>}
        {draft.showPrice && <th>Amount <small>{draft.currency}</small></th>}
        <th>Notes</th><th><span className="quote-sr-only">Actions</span></th>
      </tr></thead>
      <tbody>{products.map((product) => {
        const line = draft.lines[product.sku] || emptyLine();
        const cover = product.assets[0];
        const price = priceCents(line.price); const qty = quantityValue(line.quantity);
        const quotable = isQuotable(product);
        return <tr key={product.sku} className={selected.has(product.sku) ? "is-in-quote" : ""}>
          <td>{editor ? <div className="quote-row-order"><span>{draft.order.indexOf(product.sku) + 1}</span><button type="button" aria-label={`Move ${product.sku} up`} disabled={draft.order.indexOf(product.sku) === 0} onClick={() => onMove?.(product.sku, -1)}><ArrowUp size={14} /></button><button type="button" aria-label={`Move ${product.sku} down`} disabled={draft.order.indexOf(product.sku) === draft.order.length - 1} onClick={() => onMove?.(product.sku, 1)}><ArrowDown size={14} /></button></div> : <input type="checkbox" aria-label={`Select ${product.sku} for quotation`} checked={selected.has(product.sku)} disabled={!quotable} onChange={(e) => onToggle([product.sku], e.target.checked)} />}</td>
          <td><div className="quote-product-cell"><ImageTag className="quote-product-image" onClick={editor ? undefined : () => onSelect(product.sku)} aria-label={editor ? undefined : `View ${product.name}`}>
            {cover && cover.kind !== "document" ? <AssetImage src={thumbnailVariantUrl(cover.thumbnailUrl, "small")} alt={product.name} loading="lazy" /> : <FilePdf size={28} />}
          </ImageTag><div><SkuTag className="quote-sku" onClick={editor ? undefined : () => onSelect(product.sku)}>{product.sku}</SkuTag>{editor ? <input className="quote-name-input" aria-label={`Product name for ${product.sku}`} value={line.name || product.name} maxLength={160} onChange={(e) => onEdit(product.sku, { name: e.target.value })} /> : <button className="quote-product-name" onClick={() => onSelect(product.sku)}>{line.name || product.name}</button>}<small>{product.assetCount ?? product.assets.length} assets</small></div></div></td>
          {draft.showPrice && <td><input className="quote-price-input" aria-label={`Unit price for ${product.sku}`} inputMode="decimal" placeholder="Quote" value={line.price} disabled={!quotable} maxLength={10} onChange={(e) => { if (/^\d{0,7}(\.\d{0,2})?$/.test(e.target.value)) onEdit(product.sku, { price: e.target.value }); }} onBlur={() => { if (line.price.endsWith(".")) onEdit(product.sku, { price: line.price.slice(0, -1) }); }} /></td>}
          <td><input className="quote-quantity-input" aria-label={`Quantity for ${product.sku}`} inputMode="numeric" placeholder="—" value={line.quantity} disabled={!quotable} maxLength={6} onChange={(e) => { if (/^\d{0,6}$/.test(e.target.value)) onEdit(product.sku, { quantity: e.target.value }); }} /></td>
          {draft.showBrand && <td className="quote-meta-cell">{product.brand || "—"}</td>}
          {draft.showCategory && <td className="quote-meta-cell">{product.otherCategory || product.category || "—"}</td>}
          {draft.showPrice && <td className="quote-amount">{price !== null && qty !== null ? formatMoney(price * qty, draft.currency) : "—"}</td>}
          <td><input className="quote-note-input" aria-label={`Note for ${product.sku}`} placeholder="Add a note" value={line.note} disabled={!quotable} maxLength={160} onChange={(e) => onEdit(product.sku, { note: e.target.value })} /></td>
          <td><div className="quote-row-actions">{editor ? <button aria-label={`Remove ${product.sku} from quotation`} onClick={() => onToggle([product.sku], false)}><X size={17} /></button> : <><button aria-label={`${product.isFavorite ? "Remove" : "Add"} ${product.sku} ${product.isFavorite ? "from" : "to"} favorites`} onClick={() => onFavorite?.(product)}><Heart size={18} weight={product.isFavorite ? "fill" : "regular"} /></button><button aria-label={`Open ${product.sku} in Drive`} onClick={() => onOpenDrive?.(product)}><ArrowSquareOut size={18} /></button></>}</div></td>
        </tr>;
      })}</tbody>
    </table>
  </div>;
}
