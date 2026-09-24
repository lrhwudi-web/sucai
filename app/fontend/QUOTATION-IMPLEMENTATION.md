# Product catalog workbook

Product Catalog sits immediately beside Asset Library in the main header and opens a full-width workbook at `#quotation`. The asset library retains its card/list presentation. Existing account permissions, admin panels, favorites and detail drawers remain in their existing modules.

## Customer flow

1. Switch between Asset Library and Product Catalog in the main header.
2. The catalog uses a merged title, blue-gray headings, black grid lines, gray row/column headers, a name box, formula bar, compact toolbar and bottom worksheet tabs. Columns follow the supplied catalog: BRAND, SKU, ITEM, CATEGORY, PHOTO, two price tiers, MSRP, NOTE, INVENTORY, ORDER QTY and AMOUNT.
3. Single-click selects; double-click, F2 or typing edits. Escape cancels. Enter and Tab commit and move. Arrow keys navigate; Shift extends the selection. Name-box addresses such as F3:G8 select a rectangle.
4. Drag to select a rectangle. Ctrl+C/Ctrl+V copy/paste TSV with quoted multiline cells. Delete clears the range. Invalid numeric pastes are rejected atomically. SKU and photo cells are read-only; importing Excel can replace photos for matching SKUs.
5. Drag the bottom-right fill handle vertically to repeat values, extend a number series, or copy formulas. Row and column borders resize cells. Freeze holds columns through PHOTO, including SKU. Header filter buttons toggle an Excel-style popup open/closed when clicked again. The Columns menu hides or restores columns.
6. Undo/redo retains up to 60 operations during the session. A range paste, clear, fill, resize or Excel import is one operation. Positive quantities select products. The Selected products tab follows selection order; the Excel export review provides up/down controls for customer catalog ordering.
7. The single Export Excel button opens a review dialog. It defaults to selected products when present, otherwise the current worksheet. Customers can switch the scope, adjust the selected-product order, and choose visible columns. The .xlsx file retains compressed pictures, editable data, amount formulas, hidden columns, dimensions and freeze panes. Company/contact/reference are saved as workbook properties and a note on the catalog title. The reference also names the downloaded file. A prepared-file link remains available if automatic downloading does not start.
8. Import reads .xlsx files and matches existing authorized products by SKU. Unknown/duplicate SKUs are skipped with a count. Numeric formula cells use cached values; external workbook links and macros are not executed. The source template's 本地总库存 column maps to INVENTORY. When a salesperson imports a workbook, its known SKU row order and publishable table contents are saved as that salesperson's customer table automatically.
9. Catalog PDF export has been removed from the product flow. There is one Excel export entry rather than separate worksheet and PDF buttons. Legacy PDF utilities are unreferenced by the app and are not included in the JavaScript build.
10. Double-clicking a PHOTO cell, or selecting it and pressing Enter, opens the existing right-side product detail drawer for that SKU. The drawer loads product details on demand, shows the imported catalog picture first when present, then every customer-visible website image, and excludes videos, documents and internal assets. Its large preview, thumbnail strip, current-file panel, Open original and Open in Drive actions are reused from Asset Library. Catalog preview mode hides favorites, cover changes, theme editing and comments so browsing remains read-only; the close button returns to the worksheet.
11. Salespeople can open **Arrange** in the workbook toolbar and group the full customer table by category, series/theme, product set, brand or SKU. The existing order is preserved within each group. Row handles in the gray number gutter then support custom drag reordering and keyboard up/down movement. Grouping and manual moves save automatically to the salesperson's customer table; customers do not see the management controls.

## Column filters

The popup offers ascending/descending worksheet sorting, a content tab, text conditions, and Clear filter. The content list has distinct-value checkboxes, an indeterminate Select all, explicit (Blanks), row counts, keyword search, Name/Count list sorting and a hover/focus Only this item action. There is no 80-value truncation. Pictures are grouped as Has image or blank rather than exposing image URLs.

Checkbox edits remain pending until OK. Cancel, Escape, outside click or clicking the same header again discard pending edits. Only this item, Clear filter and worksheet sorting apply immediately and close the panel. Space-separated search words match any word without case sensitivity; OK applies checked values within the search results. Select all toggles the search results while preserving pending choices outside them. Clearing the search restores the full option list. No-match or zero-checked content searches disable OK.

Counts respect the global search, active worksheet and other column filters while retaining unchecked alternatives in the current column. Values match exactly, with OR within one column and AND between columns. Numeric columns use numeric values and AMOUNT uses evaluated results. Text conditions support contains, does not contain, equals, does not equal, begins with and ends with. Filters remain session view state. For customers, sorting is also local view state; for a salesperson managing the main Accessories sheet, sorting automatically saves that salesperson's customer-table SKU order without changing product data.

## Formula scope

The amount column accepts arithmetic, comparisons, IF, ROUND, SUM, MIN, MAX and ABS with cell references. Other text cells starting with = remain literal text. The evaluator never executes JavaScript, macros or external workbook references. Invalid and unsupported formulas show an error in the cell.

The default amount uses the 1–29 price for quantities below 30 and the 30–50 price through quantity 50. Missing prices and quantities over 50 return a blank amount; the status bar counts products needing a quote. Currency changes the denomination only, without exchange conversion.

Stored references follow their SKUs when rows are sorted or reordered. Range arguments are expanded to individual references (up to 500 cells) to preserve that association. Excluding a referenced product from the current sheet produces #REF! rather than silently pointing to another product. Include all referenced products when exporting a custom cross-product formula. This is a catalog workbook, not a complete implementation of every Excel function.

## Persistence and access

Each admin salesperson owns one server-stored customer table. Customers created by that salesperson receive its SKU order, title, currency, published cell values and column/row layout. Ascending or descending sorting on the main Accessories sheet automatically saves only the resulting full product order to that salesperson's customer table. Arrange grouping and manual row movement use the same order-only save path, so they never publish unfinished prices, notes or layout edits. Manual movement is available on the complete Accessories view; the UI asks the salesperson to clear search and filters first so hidden rows cannot be moved accidentally. **Publish table changes** sends prices, notes, title, currency, columns and layout changes to customers, and importing a local Excel workbook replaces and publishes the table in one step. Another salesperson's table and customers stay outside their management scope; a super administrator can still view all customers. Existing customers without a recorded creator retain the default catalog order.

Customer-specific company/contact/reference, selected-product order, quantities and custom amount formulas remain in that customer's browser draft. They are merged over the latest salesperson template and never published back to other customers. The server template also excludes embedded photo data and uses authorized website product images, avoiding a large workbook payload. Undo history stays in memory.

The browser draft remains saved per account in localStorage for quick restoration. The workbook compares its customer-visible content with the last published server version. When they differ, the file bar shows `Unpublished table changes · publish before closing`, highlights and enables **Publish table changes**, and registers a browser close/refresh warning. Publishing clears the warning. Customer-private company/contact/reference, selection, quantities, formulas and imported photo data do not trigger this administrator warning. Imported photos are compressed to white-backed JPEG thumbnails of at most 360 pixels for the importing salesperson's local editing and Excel export. The UI reports storage failures so the user can export before closing the tab.

Prices start blank because the product API does not provide a price source. MSRP is never substituted for a missing unit price. The supplied template also has blank tier-price cells. Up to 5,000 edited/selected products are retained; .xlsx imports are bounded at 80 MB and 10,000 source rows.

Exports intersect with available product access and re-fetch product details through the authenticated endpoint. Non-product collections cannot enter a quote. Only non-internal product thumbnails are exported; original files, source paths and credentials are excluded. Unavailable photos are reported. Session/access failures abort the export.

The product detail drawer is separate from worksheet data and export media preparation. Opening it or switching thumbnails never changes the PHOTO cell, selected products, draft, saved salesperson table or the image chosen by Excel export.



## Validation and integration

Run `pnpm run build` and `node --experimental-strip-types --test tests/*.test.mjs` using Node 24. See WORKBOOK-VERIFICATION.md for browser checks. The optional original-template test requires the supplied local file; the browser review server and product fixtures are staging-only and are not included in the production integration.

The staging workspace is `Documents/New project/work/sales-catalog-order`. `tests/preview_sales_server.py` serves dist with a temporary local catalog-order API and product fixtures at port 4187. The production source uses the existing API-enabled Vite configuration and FastAPI deployment workflow. Database initialization adds the creator relationship and salesperson catalog table idempotently. This update is integrated into local source only, without publishing online.
