import type { MaterialProduct } from "../types";
import type { QuoteDraft } from "./quotation";
import { buildCatalogXlsx, type CatalogXlsxOptions } from "./excelCatalog";
import { COLUMNS, type WorkbookColumn } from "./workbookData";
import { downloadBytes, preparePictures } from "./workbookMedia";

export async function createCatalogExcel(draft: QuoteDraft, products: MaterialProduct[], onProgress: (message: string) => void, columns: WorkbookColumn[] = COLUMNS, options: CatalogXlsxOptions = {}) {
  const photos = await preparePictures(draft, products, onProgress);
  onProgress("Creating Excel catalog…");
  const bytes = await buildCatalogXlsx(draft, products, photos, columns, options);
  const name = (draft.reference || "Craftsman_Golf_Catalog").replace(/[^\p{L}\p{N}_ -]/gu, "_").trim().slice(0, 70);
  return {
    bytes,
    blob: new Blob([new Uint8Array(bytes)], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }),
    name: `${name || "Craftsman_Golf_Catalog"}.xlsx`,
    size: bytes.length,
    missingImages: products.length - photos.size,
  };
}

export async function downloadCatalogExcel(draft: QuoteDraft, products: MaterialProduct[], onProgress: (message: string) => void, columns: WorkbookColumn[] = COLUMNS) {
  const result = await createCatalogExcel(draft, products, onProgress, columns);
  return {
    ...downloadBytes(result.bytes, result.name, result.blob.type),
    missingImages: result.missingImages,
  };
}
