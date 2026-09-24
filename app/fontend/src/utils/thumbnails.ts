export type ThumbnailVariant = "small" | "card" | "drawer";

export function thumbnailVariantUrl(url: string, variant: ThumbnailVariant): string {
  if (!url || !url.includes("/thumb/")) return url;

  const [urlWithoutHash, hash = ""] = url.split("#", 2);
  const queryIndex = urlWithoutHash.indexOf("?");
  const path = queryIndex >= 0 ? urlWithoutHash.slice(0, queryIndex) : urlWithoutHash;
  const query = queryIndex >= 0 ? urlWithoutHash.slice(queryIndex + 1) : "";
  const params = new URLSearchParams(query);
  params.set("variant", variant);
  const suffix = hash ? `#${hash}` : "";
  return `${path}?${params.toString()}${suffix}`;
}
