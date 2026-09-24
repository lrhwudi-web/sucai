import type { MaterialAsset, MaterialProduct } from "../types";

export function visibleGalleryImages(product: MaterialProduct, importedPhoto = ""): MaterialAsset[] {
  const images: MaterialAsset[] = [];
  if (importedPhoto.startsWith("data:image/")) {
    images.push({
      id: `catalog-photo-${product.sku}`,
      name: "Imported catalog image",
      kind: "image",
      mimeType: importedPhoto.slice(5, importedPhoto.indexOf(";")) || "image/jpeg",
      thumbnailUrl: importedPhoto,
      previewUrl: importedPhoto,
      downloadUrl: "",
    });
  }

  const seen = new Set(images.map((image) => image.id));
  for (const asset of product.assets) {
    if (asset.kind !== "image" || asset.internalOnly || (!asset.thumbnailUrl && !asset.previewUrl)) continue;
    const identity = asset.id || asset.previewUrl || asset.thumbnailUrl;
    if (seen.has(identity)) continue;
    seen.add(identity);
    images.push(asset);
  }
  return images;
}
