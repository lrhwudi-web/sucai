import { mockProducts } from "../data/mockData";
import {
  DEFAULT_THEME_OPTIONS,
  type ApiAsset,
  type ApiProduct,
  type ApiProductDetail,
  type MaterialAsset,
  type MaterialProduct,
  type ThemeOption,
} from "../types";
import { normalizeProductTaxonomy } from "../utils/category";
import { apiEnabled } from "./auth";

interface ProductPage {
  products: ApiProduct[];
  total: number;
  next_offset: number;
  has_more: boolean;
  catalog_snapshot?: string;
}

export interface DriveCopyState {
  state: "idle" | "building" | "ready" | "error";
  progress: number;
  job_id?: string;
  error?: string;
  folder_id?: string;
  folder_url?: string;
  expires_at?: string;
  completed?: number;
  total?: number;
}

export interface ProductMessage {
  id: number;
  sku: string;
  body: string;
  created_at: string;
}

export class SessionExpiredError extends Error {}

export interface MissingSkuNotificationResult {
  notified: boolean;
  duplicate: boolean;
  recipientName: string;
}

async function apiError(response: Response, fallback: string): Promise<Error> {
  if (response.status === 401) return new SessionExpiredError("Your session has expired. Please sign in again.");
  if (response.headers.get("content-type")?.includes("application/json")) {
    const payload = await response.json() as { detail?: string };
    return new Error(payload.detail || fallback);
  }
  return new Error(`${fallback} (${response.status})`);
}

export async function reportMissingSkus(
  skus: string[],
  searchedCount: number,
  source: "batch_search" | "excel_import" = "batch_search",
): Promise<MissingSkuNotificationResult> {
  if (!apiEnabled() || !skus.length) {
    return { notified: false, duplicate: false, recipientName: "刘芮华" };
  }
  const response = await fetch("/api/catalogue/missing-skus", {
    method: "POST",
    credentials: "include",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ skus, searched_count: searchedCount, source }),
  });
  if (!response.ok) throw await apiError(response, "未找到的 SKU 暂时无法通知管理员。");
  const payload = await response.json() as {
    notified: boolean;
    duplicate: boolean;
    recipient_name?: string;
  };
  return {
    notified: Boolean(payload.notified),
    duplicate: Boolean(payload.duplicate),
    recipientName: payload.recipient_name || "刘芮华",
  };
}

function formatUpdatedAt(value?: string): string {
  if (!value) return "Synced";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function versionedUrl(url: string, version?: string): string {
  if (!version || url.startsWith("/assets/")) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}v=${encodeURIComponent(version)}`;
}

function fallbackAsset(product: ApiProduct): MaterialAsset {
  const id = product.cover_id || `${product.sku}-cover`;
  const fallback = "/assets/monkey-driver-cover.jpg";
  const isCatalogDocument = !product.cover_id && product.other === "Product Catalogs";
  return {
    id,
    name: `${product.sku} cover`,
    kind: isCatalogDocument ? "document" : product.cover_mime?.startsWith("video/") ? "video" : "image",
    mimeType: isCatalogDocument ? "application/pdf" : product.cover_mime || "image/jpeg",
    thumbnailUrl: product.cover_id
      ? versionedUrl(`/thumb/${encodeURIComponent(product.cover_id)}`, product.cover_modified_time || product.modified_time)
      : isCatalogDocument ? "" : fallback,
    previewUrl: product.cover_id
      ? versionedUrl(`/media/${encodeURIComponent(product.cover_id)}`, product.cover_modified_time || product.modified_time)
      : isCatalogDocument ? "" : fallback,
    downloadUrl: product.cover_id ? `/download/${encodeURIComponent(product.cover_id)}` : isCatalogDocument ? "" : fallback,
  };
}

function mapAsset(asset: ApiAsset): MaterialAsset {
  return {
    id: asset.id,
    name: asset.name,
    kind: asset.kind,
    mimeType: asset.mime_type,
    thumbnailUrl: versionedUrl(asset.thumbnail_url, asset.modified_time),
    previewUrl: versionedUrl(asset.preview_url, asset.modified_time),
    downloadUrl: asset.download_url,
    size: asset.size,
    path: asset.path,
    assetType: asset.asset_type,
    internalOnly: asset.internal_only,
  };
}

function fromApiCard(product: ApiProduct): MaterialProduct {
  const taxonomy = normalizeProductTaxonomy(product.brand, product.category, product.other);
  const otherCategory = product.other && product.other !== "No Brand" ? product.other : "";
  return {
    sku: product.sku,
    name: product.name || "English name not set",
    chineseName: product.chinese_name || "",
    listingDate: product.listing_date || "",
    brand: taxonomy.brand,
    category: taxonomy.category,
    categoryGroup: product.category_group || "",
    otherCategory,
    material: otherCategory ? "Other assets" : taxonomy.material,
    batch: product.asset_types?.join(" · ") || "Drive index",
    permission: product.internal_count ? "internal" : "public",
    owner: product.owner || "Drive index",
    updatedAt: formatUpdatedAt(product.modified_time),
    drivePath: product.drive_path || `Google Drive / ${product.brand || "Unassigned"} / ${product.category || "Unassigned"} / ${product.sku}`,
    assets: [fallbackAsset(product)],
    coverId: product.cover_id || undefined,
    assetCount: product.file_count || 0,
    imageCount: product.image_count || 0,
    videoCount: product.video_count || 0,
    documentCount: product.pdf_count || 0,
    setCode: product.set_code || "",
    themes: product.themes || [],
    assetTypes: product.asset_types || [],
    isFavorite: Boolean(product.is_favorite),
    detailsLoaded: false,
    availableInventory: typeof product.available_inventory === "number" ? product.available_inventory : undefined,
    salesWarehouseName: product.sales_warehouse_name || "",
    salesWarehouseInventory: typeof product.sales_warehouse_inventory === "number" ? product.sales_warehouse_inventory : undefined,
    salesWarehouseAge181365: typeof product.sales_warehouse_age_181_365 === "number" ? product.sales_warehouse_age_181_365 : undefined,
    salesWarehouseAge366Plus: typeof product.sales_warehouse_age_366_plus === "number" ? product.sales_warehouse_age_366_plus : undefined,
    totalPendingQc: typeof product.total_pending_qc === "number" ? product.total_pending_qc : undefined,
    totalPendingArrival: typeof product.total_pending_arrival === "number" ? product.total_pending_arrival : undefined,
    inventoryState: product.inventory_state,
    inventoryUpdatedAt: product.inventory_updated_at || "",
  };
}

function fromApiDetail(product: ApiProductDetail): MaterialProduct {
  const card = fromApiCard(product);
  const assets = product.assets.map(mapAsset);
  const orderedAssets = card.coverId
    ? [...assets].sort((left, right) => Number(right.id === card.coverId) - Number(left.id === card.coverId))
    : assets;
  return {
    ...card,
    assets: orderedAssets.length ? orderedAssets : card.assets,
    detailsLoaded: true,
  };
}

export async function loadProducts(
  onProgress?: (products: MaterialProduct[]) => void,
): Promise<{ products: MaterialProduct[]; source: "api" | "demo" }> {
  if (!apiEnabled()) {
    return {
      products: mockProducts.map((product) => ({
        ...product,
        ...normalizeProductTaxonomy(product.brand, product.category, product.material),
        otherCategory: product.otherCategory || "",
        themes: product.themes || [],
        assetTypes: product.assetTypes || [...new Set(product.assets.map((asset) => (
          asset.assetType || (asset.kind === "ugc" ? "kol_ugc" : asset.kind)
        )))],
        detailsLoaded: true,
      })),
      source: "demo",
    };
  }

  const products: MaterialProduct[] = [];
  let offset = 0;
  let hasMore = true;
  let catalogSnapshot = "";
  while (hasMore) {
    const query = new URLSearchParams({ limit: "250", offset: String(offset) });
    if (catalogSnapshot) query.set("catalog_snapshot", catalogSnapshot);
    const response = await fetch(`/api/products?${query}`, {
      headers: { Accept: "application/json" },
      credentials: "include",
    });
    if (!response.ok) throw await apiError(response, "The product library could not be loaded.");
    const payload = await response.json() as ProductPage;
    products.push(...(payload.products || []).map(fromApiCard));
    catalogSnapshot = payload.catalog_snapshot || catalogSnapshot;
    onProgress?.([...products]);
    hasMore = Boolean(payload.has_more);
    if (!hasMore) break;
    if (payload.next_offset <= offset) throw new Error("The product library returned an invalid page cursor.");
    offset = payload.next_offset;
  }
  return { products, source: "api" };
}

export async function loadProductDetail(sku: string): Promise<MaterialProduct> {
  if (!apiEnabled()) {
    const product = mockProducts.find((item) => item.sku === sku);
    if (!product) throw new Error("Product not found.");
    return {
      ...product,
      ...normalizeProductTaxonomy(product.brand, product.category, product.material),
      detailsLoaded: true,
    };
  }
  const response = await fetch(`/api/products/${encodeURIComponent(sku)}`, {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw await apiError(response, "The product details could not be loaded.");
  const payload = await response.json() as { product: ApiProductDetail };
  return fromApiDetail(payload.product);
}

export async function loadThemeOptions(): Promise<ThemeOption[]> {
  if (!apiEnabled()) return DEFAULT_THEME_OPTIONS;
  const response = await fetch("/api/themes", {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw await apiError(response, "Theme options could not be loaded.");
  const payload = await response.json() as { themes?: ThemeOption[] };
  return payload.themes?.length ? payload.themes : DEFAULT_THEME_OPTIONS;
}

export async function setProductThemes(sku: string, themes: string[]): Promise<void> {
  if (!apiEnabled()) return;
  const form = new FormData();
  form.append("skus", sku);
  form.set("themes", themes.join("|"));
  form.set("update_themes", "true");
  const response = await fetch("/api/admin/products/bulk-metadata", {
    method: "POST",
    body: form,
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw await apiError(response, "The product themes could not be updated.");
}

export async function prepareProductDriveCopy(sku: string): Promise<DriveCopyState> {
  if (!apiEnabled()) return { state: "error", progress: 0, error: "Drive export requires a connected account." };
  const response = await fetch(`/sku/${encodeURIComponent(sku)}/drive/prepare`, {
    method: "POST",
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw await apiError(response, "The Drive folder could not be prepared.");
  return response.json() as Promise<DriveCopyState>;
}

export async function getProductDriveCopyStatus(sku: string, jobId: string): Promise<DriveCopyState> {
  const query = new URLSearchParams({ job_id: jobId });
  const response = await fetch(`/sku/${encodeURIComponent(sku)}/drive/status?${query}`, {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw await apiError(response, "The Drive folder status could not be checked.");
  return response.json() as Promise<DriveCopyState>;
}

export async function loadMyProductMessages(sku: string): Promise<ProductMessage[]> {
  if (!apiEnabled()) return [];
  const response = await fetch(`/api/products/${encodeURIComponent(sku)}/messages`, {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw await apiError(response, "Your messages could not be loaded.");
  const payload = await response.json() as { messages: ProductMessage[] };
  return payload.messages || [];
}

export async function addProductMessage(sku: string, message: string): Promise<ProductMessage> {
  if (!apiEnabled()) {
    return { id: Date.now(), sku, body: message, created_at: new Date().toISOString() };
  }
  const form = new FormData();
  form.set("message", message);
  const response = await fetch(`/api/products/${encodeURIComponent(sku)}/messages`, {
    method: "POST",
    body: form,
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw await apiError(response, "Your message could not be sent.");
  const payload = await response.json() as { message: ProductMessage };
  return payload.message;
}

export async function recordOriginalOpen(sku: string, fileId: string): Promise<void> {
  if (!apiEnabled()) return;
  const form = new FormData();
  form.set("sku", sku);
  form.set("file_id", fileId);
  const response = await fetch("/api/activity/original-open", {
    method: "POST",
    body: form,
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw await apiError(response, "The original-view activity could not be recorded.");
}

export async function setProductFavorite(sku: string, favorite: boolean): Promise<boolean> {
  if (!apiEnabled()) return favorite;
  const form = new FormData();
  form.set("favorite", String(favorite));
  const response = await fetch(`/api/products/${encodeURIComponent(sku)}/favorite`, {
    method: "POST",
    body: form,
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw await apiError(response, "Your favorites could not be updated.");
  const payload = await response.json() as { is_favorite: boolean };
  return payload.is_favorite;
}

export async function setProductCover(sku: string, fileId: string): Promise<string> {
  if (!apiEnabled()) return fileId;
  const form = new FormData();
  form.set("file_id", fileId);
  const response = await fetch(`/api/admin/products/${encodeURIComponent(sku)}/cover`, {
    method: "POST",
    body: form,
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw await apiError(response, "The product cover could not be updated.");
  const payload = await response.json() as { cover_file_id: string };
  return payload.cover_file_id;
}
