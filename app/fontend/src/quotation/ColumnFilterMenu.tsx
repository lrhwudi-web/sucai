import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Funnel, FunnelX, MagnifyingGlass, SortAscending, SortDescending, X } from "@phosphor-icons/react";
import { matchesFilter, searchOptions, selectedValueFilter, toggleOptions, type ColumnFilter, type FilterOption, type TextOperator } from "./columnFilters.ts";
import "./columnFilter.css";

interface Props {
  column: string; label: string; x: number; y: number; options: FilterOption[];
  filter?: ColumnFilter; sortDirection?: 1 | -1;
  onApply: (filter?: ColumnFilter) => void; onSort: (direction: 1 | -1) => void; onClose: () => void;
}

export function ColumnFilterMenu({ column, label, x, y, options, filter, sortDirection, onApply, onSort, onClose }: Props) {
  const [mode, setMode] = useState<"values" | "text">(filter?.kind === "text" ? "text" : "values");
  const [selected, setSelected] = useState(() => new Set(options.filter(option => matchesFilter(option.value, filter)).map(option => option.value)));
  const [search, setSearch] = useState("");
  const [optionSort, setOptionSort] = useState<{ by: "name" | "count"; direction: 1 | -1 }>({ by: "name", direction: 1 });
  const [operator, setOperator] = useState<TextOperator>(filter?.kind === "text" ? filter.operator : "contains");
  const [query, setQuery] = useState(filter?.kind === "text" ? filter.query : "");
  const all = useRef<HTMLInputElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const shown = useMemo(() => searchOptions(options, search).sort((a, b) => {
    const names = a.value.localeCompare(b.value, undefined, { numeric: true });
    return (optionSort.by === "count" ? (a.count - b.count) || names : names) * optionSort.direction;
  }), [options, search, optionSort]);
  const checkedCount = shown.filter(option => selected.has(option.value)).length;
  const totalCount = shown.reduce((total, option) => total + option.count, 0);
  const allChecked = shown.length > 0 && checkedCount === shown.length;
  useEffect(() => { if (all.current) all.current.indeterminate = checkedCount > 0 && !allChecked; }, [checkedCount, allChecked, mode]);
  useEffect(() => {
    const opener = document.querySelector<HTMLElement>(`[aria-label="Filter ${column} column"]`), element = panel.current;
    return () => { if (document.activeElement === document.body || element?.contains(document.activeElement)) opener?.focus({ preventScroll: true }); };
  }, [column]);
  const sortOptions = (by: "name" | "count") => setOptionSort(current => ({ by, direction: current.by === by ? (current.direction === 1 ? -1 : 1) : by === "name" ? 1 : -1 }));
  const apply = () => onApply(mode === "values" ? selectedValueFilter(selected, options, search) : { kind: "text", operator, query });
  return <div ref={panel} id="workbook-column-filter" role="dialog" aria-label={`Filter ${column}`} className="wb-column-filter" style={{ left: x, top: y, maxHeight: `calc(100dvh - ${y + 8}px)` }} onKeyDown={event => {
    if (event.key === "Escape") { event.preventDefault(); onClose(); }
    if (event.key === "Enter" && event.target instanceof HTMLInputElement && event.target.type !== "checkbox") { event.preventDefault(); if (mode === "text" || checkedCount > 0) apply(); }
  }}>
    <div className="wbf-sort-bar">
      <button aria-pressed={sortDirection === 1} onClick={() => onSort(1)}><SortAscending size={21}/><span>Ascending</span></button>
      <button aria-pressed={sortDirection === -1} onClick={() => onSort(-1)}><SortDescending size={21}/><span>Descending</span></button>
      <span className="wbf-column-name" title={label}>{label}</span>
      <button className="wbf-close" aria-label="Close column filter" onClick={onClose}><X size={16}/></button>
    </div>
    <div className="wbf-tabs">
      <div role="tablist" aria-label="Filter type">
        <button role="tab" aria-selected={mode === "values"} onClick={() => setMode("values")}>By content</button>
        <button role="tab" aria-selected={mode === "text"} onClick={() => setMode("text")}><Funnel size={19}/>Text filters</button>
      </div>
      <button className="wbf-clear" disabled={!filter} onClick={() => onApply(undefined)}><FunnelX size={18}/>Clear filter</button>
    </div>
    {mode === "values" ? <div className="wbf-content">
      <div className="wbf-search-bar">
        <label className="wbf-search"><MagnifyingGlass size={20}/><input autoFocus aria-label="Search filter values" placeholder="Search any keywords, space separated" value={search} onChange={event => setSearch(event.target.value)}/></label>
        {search && <button className="wbf-search-clear" aria-label="Clear value search" onClick={() => setSearch("")}><X size={14}/></button>}
      </div>
      <div className="wbf-list-tools">
        <label className="wbf-select-all"><input ref={all} type="checkbox" checked={allChecked} disabled={!shown.length} onChange={event => setSelected(current => toggleOptions(current, shown, event.target.checked))}/><span>Select all</span><span className="wbf-count">({totalCount})</span></label>
        <button aria-label="Sort filter values by name" aria-pressed={optionSort.by === "name"} onClick={() => sortOptions("name")}>Name{optionSort.by === "name" && (optionSort.direction === 1 ? <ArrowUp size={14}/> : <ArrowDown size={14}/>)}</button>
        <button aria-label="Sort filter values by count" aria-pressed={optionSort.by === "count"} onClick={() => sortOptions("count")}>Count{optionSort.by === "count" && (optionSort.direction === 1 ? <ArrowUp size={14}/> : <ArrowDown size={14}/>)}</button>
      </div>
      <div className="wbf-options" role="group" aria-label="Column values">
        {shown.map(option => <div className="wbf-option" key={option.value}>
          <label title={`${option.value || "(Blanks)"} (${option.count})`}><input type="checkbox" aria-label={option.value || "(Blanks)"} checked={selected.has(option.value)} onChange={event => setSelected(current => toggleOptions(current, [option], event.target.checked))}/><span className="wbf-option-value">{option.value || "(Blanks)"}</span><span className="wbf-count">({option.count})</span></label>
          <button className="wbf-only" aria-label={`Only filter ${option.value || "(Blanks)"}`} onClick={() => onApply({ kind: "values", values: [option.value] })}>Only this item</button>
        </div>)}
        {!shown.length && <p className="wbf-empty">No matching values.</p>}
      </div>
    </div> : <div className="wbf-text-content">
      <label>Show rows where {label.toLowerCase()}<select aria-label="Text filter condition" value={operator} onChange={event => setOperator(event.target.value as TextOperator)}>
        <option value="contains">Contains</option><option value="notContains">Does not contain</option><option value="equals">Equals</option><option value="notEquals">Does not equal</option><option value="startsWith">Begins with</option><option value="endsWith">Ends with</option>
      </select></label>
      <input autoFocus aria-label="Text filter value" value={query} onChange={event => setQuery(event.target.value)} placeholder="Enter text or a value"/>
      <p>Text matching is not case sensitive. Use Equals with an empty value to show blank cells.</p>
    </div>}
    <div className="wbf-footer"><span aria-live="polite">{mode === "values" ? `${checkedCount} of ${shown.length} values selected` : "Apply to this column"}</span><button className="wbf-apply" disabled={mode === "values" && !checkedCount} onClick={apply}>OK</button><button className="wbf-cancel" onClick={onClose}>Cancel</button></div>
  </div>;
}
