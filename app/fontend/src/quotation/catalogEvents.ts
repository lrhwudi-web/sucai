import { apiEnabled } from "../services/auth";

export type CatalogEvent = "catalog_view" | "search" | "product_open" | "product_added" | "product_removed" | "checkout_open";

export function recordCatalogEvent(eventType: CatalogEvent, sku = "") {
  if (!apiEnabled()) return;
  void fetch("/api/catalog/events", {
    method: "POST",
    credentials: "include",
    keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_type: eventType, sku }),
  }).catch(() => { /* Analytics must never interrupt browsing or ordering. */ });
}
