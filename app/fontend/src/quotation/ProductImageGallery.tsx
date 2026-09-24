import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { ProductDrawer } from "../components/ProductDrawer";
import { loadProductDetail } from "../services/materials";
import type { MaterialAsset, MaterialProduct } from "../types";
import { visibleGalleryImages } from "./galleryImages";

interface Props {
  product: MaterialProduct;
  importedPhoto?: string;
  onClose: () => void;
  onOpenDrive: () => void;
  canSetCover: boolean;
  onSetCover: (product: MaterialProduct, asset: MaterialAsset) => Promise<void>;
  onNotify: (message: string) => void;
}

export function ProductImageGallery({ product, importedPhoto = "", onClose, onOpenDrive, canSetCover, onSetCover, onNotify }: Props) {
  const [detail, setDetail] = useState(product);
  const images = useMemo(() => visibleGalleryImages(detail, importedPhoto), [detail, importedPhoto]);
  const fallbackImages = useMemo(() => visibleGalleryImages(product, importedPhoto), [importedPhoto, product]);
  const drawerProduct = useMemo(() => ({ ...detail, assets: images.length ? images : fallbackImages }), [detail, fallbackImages, images]);

  useEffect(() => {
    let mounted = true;
    setDetail(product);
    if (product.detailsLoaded) return () => { mounted = false; };
    loadProductDetail(product.sku)
      .then((loaded) => { if (mounted) setDetail(loaded); })
      .catch(() => { if (mounted) onNotify("More product images could not be loaded. Try again after refreshing the page."); });
    return () => { mounted = false; };
  }, [onNotify, product, product.sku]);

  return createPortal(
    <div className="wb-drawer-layer">
      <ProductDrawer
        product={drawerProduct}
        onClose={onClose}
        onOpenDrive={onOpenDrive}
        onToggleFavorite={() => undefined}
        isAdmin={canSetCover}
        themeOptions={[]}
        canSetCoverAsset={(asset) => !asset.id.startsWith("catalog-photo-")}
        onSetCover={async (asset) => {
          await onSetCover(product, asset);
          setDetail((current) => ({
            ...current,
            coverId: asset.id,
            assets: [asset, ...current.assets.filter((candidate) => candidate.id !== asset.id)],
          }));
        }}
        onSetThemes={async () => undefined}
        onNotify={onNotify}
        catalogPreview
      />
    </div>,
    document.body,
  );
}
