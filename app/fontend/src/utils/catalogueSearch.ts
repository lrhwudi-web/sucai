const SKU_TOKEN = /^(?=.*\d)[A-Z0-9][A-Z0-9._-]{2,}$/;

export interface CatalogueSearch {
  isBatchSkuSearch: boolean;
  normalizedText: string;
  skuOrder: string[];
  skuSet: Set<string>;
}

export function normalizePastedSearchText(value: string): string {
  return value.replace(/[\r\n\t]+/g, " ").replace(/\s+/g, " ").trim();
}

export function parseCatalogueSearch(value: string): CatalogueSearch {
  const normalizedText = value.trim().toLowerCase();
  const tokens = value
    .trim()
    .split(/[\s,，;；]+/)
    .filter(Boolean)
    .map((token) => token.toUpperCase());
  const isBatchSkuSearch = tokens.length > 1 && tokens.every((token) => SKU_TOKEN.test(token));
  const skuOrder = isBatchSkuSearch ? [...new Set(tokens)] : [];

  return {
    isBatchSkuSearch,
    normalizedText,
    skuOrder,
    skuSet: new Set(skuOrder),
  };
}
