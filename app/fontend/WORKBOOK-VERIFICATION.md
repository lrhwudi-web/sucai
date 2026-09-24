# Workbook verification — 4 September 2026

The local review uses 131 products extracted from the supplied Craftsman template. It runs the same built frontend as the production source, with a separate read-only API fixture. No production data or website deployment was changed during review.

## Verified interactions

- A single click selects a cell without mounting an editor. Typing and double-clicking start editing. Escape cancels without a blur event saving the cancelled text.
- Drag selection from J3 to K4 copied `145\t10\n46\t20`. Delete cleared all four cells; one Ctrl+Z restored them.
- Pasting two rows of tier prices updated F3:G4 together. Quantity 10 with price 6.90 calculated 69.00.
- Dragging K3:K4 containing 10 and 20 down to K6 produced 10, 20, 30, 40. One undo restored the two blank destination cells; redo restored 30 and 40.
- Row resize changed a 100 px row to 126 px. Column resize changed a 98 px quantity column to 61 px. Both operations were undoable.
- After horizontal scrolling, the SKU and photo cells retained sticky positions. Category-header filtering selected the four Glove Case products. Hiding and undoing the category column worked.
- Importing the original 24.6 MB workbook in the browser restored its title, photos, `NEW` notes and cached inventory (first row 145). It sent a successful catalog-order update to the server. Refreshing restored SKU 5902160 as the first row with NOTE `NEW` and INVENTORY `145`, confirming the uploaded order and values persisted.
- Sorting SKU descending on Accessories automatically sent the resulting full SKU order to the salesperson's customer table and showed `Customer table order saved. Your customers will see this order.`. SKU `8300472` moved to the first row; refreshing the page kept it first, confirming the saved order was reloaded. The header identifies `Customer table · Sales A · row order saves automatically`; **Publish table changes** is reserved for prices, notes, title, currency, columns and layout changes.
- Editing the catalog title enabled the amber **Publish table changes** button and changed the file-bar status to `Unpublished table changes · publish before closing`. Running Arrange → SKU saved the order while leaving that unpublished state intact, confirming that order saves do not publish draft content. Publishing disabled the button, restored the normal status and showed `Table changes published to your customers.`. The preview title was then restored and published cleanly.
- The browser registers a `beforeunload` warning only while customer-visible table content differs from the published server version. Customer identity fields, selections, quantities, formulas and embedded local pictures are excluded from the comparison.
- The toolbar **Arrange** menu offers Category, Series / theme, Product set, Brand and SKU. Choosing Category grouped the first five visible products under `Alignment Stick Cover` and showed `Grouped by category. Your customers will see this order.`.
- The row-3 move handle moved SKU `6015378` below SKU `5902430`, showed `Custom row order saved. Your customers will see this order.`, and the swapped order remained after refresh. Pointer dragging and keyboard arrow movement share the same tested reorder function; handles are disabled while search or filters hide rows.
- Clicking the INVENTORY filter opened one popup; clicking it again removed the popup and reset aria-expanded to false.
- The toolbar contains one Export Excel button and no PDF export button. The review includes AMOUNT, defaults to the current worksheet with no selection, and supports selected-product export.
- PHOTO cells open the existing right-side product detail drawer by double-click or Enter. The drawer loads the full product detail, keeps only customer-visible images, reuses the large preview, four-image thumbnail strip, current-file panel, Open original and Open in Drive actions, and closes from its standard close control. Selecting the second thumbnail updated both the preview and Current file. Open original now renders above the complete drawer and applies the full-screen 10 px backdrop blur to every underlying surface. Catalog preview mode omits favorites, cover/theme mutation controls and comments; it is read-only and independent of the Excel export media pipeline.

## Automated checks

`node --experimental-strip-types --test tests/*.test.mjs` covers existing application behavior plus transactional edits, clipboard quoting, numeric series, relative/absolute formula references, tier boundaries, errors, sorting, draft reload, Excel round-trips, original-template import, salesperson ordering, publishable-field separation and customer-template merging.

`tests/gallery-images.test.mjs` additionally verifies imported-photo precedence, all-image inclusion, internal/non-image exclusion, de-duplication and that gallery preparation never mutates the product data used by export.

`pnpm run build` runs TypeScript and the production Vite build. ExcelJS is loaded on demand. PDF generation and font libraries are no longer bundled into the application JavaScript. Vite still reports large optional library chunks; they do not block the build.

`pytest tests/test_sales_catalog_order.py tests/test_customer_access.py -q` covers independent salesperson tables, creator inheritance, owner-scoped customer management, optimistic revision conflicts, payload limits and legacy-customer compatibility.

## Excel-style filter follow-up

- CATEGORY lists 18 distinct values totaling 131 rows. Unchecking BALL MARKER leaves the worksheet unchanged until OK; clicking the header again closes the popup, and reopening restores the committed checks.
- Glove Case (4) plus Scorecard Holder (7) yields 11 products. BRAND then shows bigteeth (2), craftsman (3), mytag (1), No Label (5). Only filter mytag yields SKU 5902077. Cancel after clearing pending selections retains that product.
- Searching `GLOVE scorecard` lists the two matching values; OK yields the same 11 products. Clear filter restores 131. Sorting the option list by count puts BALL MARKER (23), Sliding Mitts (22), TOWEL (17) first.
- Text condition Begins with `Range` yields six products across Range Finder Case and Rangefinder Strap.
- NOTE shows (Blanks) (112) and NEW (19); selecting blanks yields 112 products. INVENTORY ascending places blanks first, then 1, 2, 2, 3, verifying numeric sorting.
- The 440 px popup is clamped within the browser viewport, with a scrolling list and visible OK/Cancel. Category header remains clickable above the popup. The preview was restored to all 131 rows, frozen PHOTO/SKU and zero selected products after review.
- `node --experimental-strip-types --test tests/column-filters.test.mjs tests/workbook.test.mjs`: 12 passing checks, including exact-value multiselect, blanks/zero, cross-column facet counts, keyword OR search, pending selection immutability, text conditions and the existing workbook/Excel import-export regressions. TypeScript and Vite build passed.
