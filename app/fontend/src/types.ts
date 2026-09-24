export type Permission = "public" | "internal";
export type AssetKind = "image" | "video" | "document" | "ugc" | "ads";
export type ViewMode = "grid" | "list";
export type SortMode = "newest" | "name" | "assets" | "category" | "sku";

export interface ThemeOption {
  id: string;
  label: string;
}

export const DEFAULT_THEME_OPTIONS: ThemeOption[] = [
  { id: "AMERICANA", label: "Americana" },
  { id: "LUCKY_CLOVER", label: "Lucky & Clover" },
  { id: "POP_CULTURE_ENTERTAINMENT", label: "Pop Culture & Entertainment" },
  { id: "FOOD_DRINKS", label: "Food & Drinks" },
  { id: "ANIMALS", label: "Animals" },
  { id: "WOMENS_GIRLS", label: "Women's & Girls" },
  { id: "SKULLS_GOTHIC", label: "Skulls & Gothic" },
  { id: "CLASSIC_RETRO", label: "Classic & Retro" },
  { id: "LIMITED_EDITION", label: "Limited Edition" },
];

export interface MaterialAsset {
  id: string;
  name: string;
  kind: AssetKind;
  mimeType: string;
  thumbnailUrl: string;
  previewUrl: string;
  downloadUrl: string;
  size?: number;
  path?: string;
  assetType?: string;
  internalOnly?: boolean;
}

export interface MaterialProduct {
  sku: string;
  name: string;
  chineseName?: string;
  listingDate?: string;
  brand: string;
  category: string;
  categoryGroup?: string;
  otherCategory: string;
  material: string;
  batch: string;
  permission: Permission;
  owner: string;
  updatedAt: string;
  drivePath: string;
  assets: MaterialAsset[];
  coverId?: string;
  assetCount?: number;
  imageCount?: number;
  videoCount?: number;
  documentCount?: number;
  setCode?: string;
  themes: string[];
  assetTypes?: string[];
  isFavorite?: boolean;
  detailsLoaded?: boolean;
  availableInventory?: number;
  salesWarehouseName?: string;
  salesWarehouseInventory?: number;
  salesWarehouseAge181365?: number;
  salesWarehouseAge366Plus?: number;
  totalPendingQc?: number;
  totalPendingArrival?: number;
  inventoryState?: "live" | "stale" | "unavailable" | "disabled";
  inventoryUpdatedAt?: string;
}

export interface ProductFilters {
  brand: string[];
  category: string[];
  theme: string[];
  other: string[];
  material: string;
  assetKind: string;
  permission: string;
}

export interface ApiProduct {
  sku: string;
  name: string;
  chinese_name?: string;
  listing_date?: string;
  brand?: string;
  category?: string;
  category_group?: string;
  other?: string;
  cover_id?: string;
  cover_mime?: string;
  cover_modified_time?: string;
  image_count?: number;
  video_count?: number;
  pdf_count?: number;
  file_count?: number;
  internal_count?: number;
  drive_path?: string;
  modified_time?: string;
  owner?: string;
  asset_types?: string[];
  kol_count?: number;
  set_code?: string;
  themes?: string[];
  is_favorite?: boolean;
  available_inventory?: number;
  sales_warehouse_name?: string;
  sales_warehouse_inventory?: number;
  sales_warehouse_age_181_365?: number;
  sales_warehouse_age_366_plus?: number;
  total_pending_qc?: number;
  total_pending_arrival?: number;
  inventory_state?: "live" | "stale" | "unavailable" | "disabled";
  inventory_updated_at?: string;
}

export interface ApiAsset {
  id: string;
  name: string;
  kind: "image" | "video" | "document";
  mime_type: string;
  size: number;
  modified_time: string;
  path: string;
  asset_type: string;
  internal_only: boolean;
  thumbnail_url: string;
  preview_url: string;
  download_url: string;
}

export interface ApiProductDetail extends ApiProduct {
  assets: ApiAsset[];
  notes?: string;
}
