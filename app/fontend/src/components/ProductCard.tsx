import {
  ArrowRight,
  ArrowSquareOut,
  Heart,
  ImageSquare,
  FilePdf,
  LockKey,
  VideoCamera,
  DownloadSimple,
} from "@phosphor-icons/react";
import type { MaterialProduct, ViewMode } from "../types";
import { thumbnailVariantUrl } from "../utils/thumbnails";
import { AssetImage } from "./AssetImage";

interface ProductCardProps {
  product: MaterialProduct;
  selected: boolean;
  view: ViewMode;
  priority?: boolean;
  onSelect: () => void;
  onOpenDrive: () => void;
  onToggleFavorite: () => void;
  downloadSelected?: boolean;
  onToggleDownload?: () => void;
  onDownload?: () => void;
}

export function ProductCard({ product, selected, view, priority = false, onSelect, onOpenDrive, onToggleFavorite, downloadSelected, onToggleDownload, onDownload }: ProductCardProps) {
  const imageCount = product.imageCount ?? product.assets.filter((asset) => asset.kind === "image").length;
  const videoCount = product.videoCount ?? product.assets.filter((asset) => asset.kind === "video").length;
  const documentCount = product.documentCount ?? product.assets.filter((asset) => asset.kind === "document").length;
  const assetCount = product.assetCount ?? product.assets.length;
  const cover = product.assets[0];
  const detailLabel = product.otherCategory || product.material.trim();

  return (
    <article className={`product-card ${selected ? "is-selected" : ""} ${view === "list" ? "is-list" : ""}`}>
      {onToggleDownload && <label className="download-select"><input type="checkbox" checked={Boolean(downloadSelected)} onChange={onToggleDownload} aria-label={`Select ${product.sku} for download`} /><span className="sr-only">Select for download</span></label>}
      <button
        className={`favorite-action ${product.isFavorite ? "is-active" : ""}`}
        onClick={onToggleFavorite}
        aria-label={product.isFavorite ? `Remove ${product.sku} from favorites` : `Add ${product.sku} to favorites`}
        title={product.isFavorite ? "Remove from favorites" : "Add to favorites"}
      >
        <Heart size={17} weight={product.isFavorite ? "fill" : "bold"} />
      </button>
      <button className="product-media" onClick={onSelect} aria-label={`View ${product.name}`}>
        {cover.kind === "document" ? (
          <div className="document-card-preview" aria-hidden="true">
            <FilePdf size={54} weight="duotone" />
            <span>PDF catalog</span>
          </div>
        ) : (
          <AssetImage
            src={thumbnailVariantUrl(cover.thumbnailUrl, "drawer")}
            alt={product.name}
            loading={priority ? "eager" : "lazy"}
            fetchPriority={selected || priority ? "high" : "low"}
          />
        )}
        {product.permission === "internal" ? (
          <span className="permission-badge internal"><LockKey size={13} weight="fill" /> Internal</span>
        ) : null}
        <span className="asset-total">{assetCount} assets</span>
      </button>

      <div className="product-card-body">
        <button className="product-title" onClick={onSelect}>
          <span className="sku-label">{product.sku}</span>
          <strong>{product.name}</strong>
          <small>{product.otherCategory ? `Other · ${product.otherCategory}` : `${product.brand} · ${product.category}`}</small>
        </button>

        <div className={`product-card-meta ${detailLabel ? "" : "is-stats-only"}`}>
          {detailLabel && <span className="product-card-context">{detailLabel}</span>}
          <span className="asset-stat"><ImageSquare size={15} weight="bold" /> {imageCount}</span>
          <span className="asset-stat"><VideoCamera size={15} weight="bold" /> {videoCount}</span>
          {documentCount > 0 && <span className="asset-stat"><FilePdf size={15} weight="bold" /> {documentCount}</span>}
        </div>

        <div className="product-card-actions">
          <button className="text-action" onClick={onSelect}>View details <ArrowRight size={16} weight="bold" /></button>
          {onDownload && <button className="round-action" onClick={onDownload} aria-label={`Download ${product.sku} assets`} title="Download assets to a folder"><DownloadSimple size={18} weight="bold" /></button>}
          <button className="round-action" onClick={onOpenDrive} aria-label={`Open ${product.sku} in Drive`} title="Open in Drive">
            <ArrowSquareOut size={18} weight="bold" />
          </button>
        </div>
      </div>
    </article>
  );
}
