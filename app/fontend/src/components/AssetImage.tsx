import { ImageSquare } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

interface AssetImageProps {
  src: string;
  previewSrc?: string;
  alt: string;
  className?: string;
  loading?: "eager" | "lazy";
  fetchPriority?: "high" | "low" | "auto";
  fallbackLabel?: string;
}

export function AssetImage({
  src,
  previewSrc,
  alt,
  className = "",
  loading = "lazy",
  fetchPriority = "low",
  fallbackLabel = "Preview unavailable",
}: AssetImageProps) {
  const [displaySrc, setDisplaySrc] = useState(src);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setDisplaySrc(src);
    setFailed(false);
  }, [src]);

  if (failed) {
    return (
      <span className={`asset-image-fallback ${className}`.trim()} role="img" aria-label={alt || fallbackLabel}>
        <ImageSquare size={24} weight="duotone" />
        <small>{fallbackLabel}</small>
      </span>
    );
  }

  return (
    <img
      className={className}
      src={displaySrc}
      alt={alt}
      loading={loading}
      decoding="async"
      fetchPriority={fetchPriority}
      onError={() => {
        if (previewSrc && previewSrc !== displaySrc) {
          setDisplaySrc(previewSrc);
        } else {
          setFailed(true);
        }
      }}
    />
  );
}
