import { MagnifyingGlass } from "@phosphor-icons/react";
import { normalizePastedSearchText } from "../utils/catalogueSearch";

interface ProductSearchProps {
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

export function ProductSearch({ value, onChange, className = "" }: ProductSearchProps) {
  return (
    <label className={["global-search", className].filter(Boolean).join(" ")}>
      <MagnifyingGlass size={20} weight="bold" aria-hidden="true" />
      <span className="sr-only">Search product assets</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onPaste={(event) => {
          const pasted = event.clipboardData.getData("text");
          if (!/[\r\n\t]/.test(pasted)) return;
          event.preventDefault();
          const start = event.currentTarget.selectionStart ?? value.length;
          const end = event.currentTarget.selectionEnd ?? start;
          const inserted = normalizePastedSearchText(pasted);
          onChange(value.slice(0, start) + inserted + value.slice(end));
        }}
        placeholder="Search by SKU, event, year or asset name"
      />
      <kbd>⌘ K</kbd>
    </label>
  );
}
