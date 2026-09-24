import type { ColumnKey } from "./workbookData.ts";

export type TextOperator = "contains" | "notContains" | "equals" | "notEquals" | "startsWith" | "endsWith";
export type ColumnFilter = { kind: "values"; values: string[] } | { kind: "text"; operator: TextOperator; query: string };
export type ColumnFilters = Partial<Record<ColumnKey, ColumnFilter>>;
export type FilterRecord<T> = { product: T; values: Record<ColumnKey, string> };
export type FilterOption = { value: string; count: number };

export function matchesFilter(value: string, filter?: ColumnFilter): boolean {
  if (!filter) return true;
  if (filter.kind === "values") return filter.values.includes(value);
  const text = value.toLocaleLowerCase(), query = filter.query.toLocaleLowerCase();
  switch (filter.operator) {
    case "contains": return text.includes(query);
    case "notContains": return !text.includes(query);
    case "equals": return text === query;
    case "notEquals": return text !== query;
    case "startsWith": return text.startsWith(query);
    case "endsWith": return text.endsWith(query);
  }
}

export function filteredRecords<T>(records: FilterRecord<T>[], filters: ColumnFilters, except?: ColumnKey) {
  const entries = Object.entries(filters) as [ColumnKey, ColumnFilter][];
  return records.filter(row => entries.every(([key, filter]) => key === except || matchesFilter(row.values[key], filter)));
}

// Facets respect the search and other columns, but retain unchecked values of this column.
export function filterOptions<T>(records: FilterRecord<T>[], filters: ColumnFilters, key: ColumnKey): FilterOption[] {
  const counts = new Map<string, number>();
  for (const row of filteredRecords(records, filters, key)) {
    const value = row.values[key];
    counts.set(value, (counts.get(value) || 0) + 1);
  }
  return [...counts].map(([value, count]) => ({ value, count }));
}

export function searchOptions(options: FilterOption[], search: string) {
  const words = search.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return options.filter(option => !words.length || words.some(word => (option.value || "(Blanks)").toLocaleLowerCase().includes(word)));
}

export function toggleOptions(selected: ReadonlySet<string>, options: FilterOption[], checked: boolean) {
  const next = new Set(selected);
  for (const { value } of options) checked ? next.add(value) : next.delete(value);
  return next;
}

export function selectedValueFilter(selected: ReadonlySet<string>, options: FilterOption[], search: string): ColumnFilter | undefined {
  const values = searchOptions(options, search).filter(option => selected.has(option.value)).map(option => option.value);
  return values.length === options.length ? undefined : { kind: "values", values };
}
