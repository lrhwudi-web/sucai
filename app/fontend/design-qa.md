# Design QA — customer-grouped order workbench

## Visual truth and state

- Source visual truth: `C:\Users\LRH\AppData\Local\Temp\codex-clipboard-07fb6ccd-2169-4a62-8779-9365d0725b19.png`.
- Removal reference: `C:\Users\LRH\AppData\Local\Temp\codex-clipboard-550bd720-0c6e-43df-8cd1-8cea6ee34364.png`.
- Source pixels: 1583 × 907 for the three-pane workbench and 730 × 274 for the heading region to remove.
- Implementation URL: `http://127.0.0.1:4187/#admin`, then `客户订单`.
- Implementation screenshot: Codex in-app browser capture emitted in the build review; the browser surface does not expose a persistent local screenshot path.
- Viewport and density: 1583 × 907 CSS pixels, device scale factor 1; source and implementation were evaluated at equal viewport dimensions without density downsampling.
- State: regular administrator `黄彩丽`; FLOG selected; two FLOG orders visible; first order selected; detail pane open.

## Full-view comparison evidence

The implementation reproduces the source's three-region hierarchy inside the existing Kairay administration shell: customer groups at left, selected-customer order table in the center, and a persistent detail/download pane at right. Scaling the source's content frame to the available admin workspace yields comparable column proportions. The warm white surfaces, thin borders, restrained elevation, burgundy selection state and yellow section accents use the site's existing tokens and visually align with the reference.

The former `SALES ORDERS`, oversized `客户订单`, and explanatory paragraph are absent from the administrator workspace. Content begins directly with the bordered workbench.

## Focused-region comparison evidence

- Customer list: each customer is an independent button with business icon, name, latest-order time and total order count. FLOG correctly shows two orders while Johan and Esteban each show one.
- Order table: the selected customer name appears beside `订单列表`; date range and order search controls are compact and aligned; selected rows use the same pale red/left-rule treatment as the source.
- Detail pane: customer identity, available contact/company/reference data, salesperson, timestamp, order number, quantity summary, filename, size and full-width `下载 Excel` action follow the source hierarchy.
- Icons are Phosphor library icons already used by the product; no placeholder, handcrafted SVG or CSS icon assets were introduced.

## Required fidelity surfaces

- Fonts and typography: existing Aptos/Segoe UI stack retained; 17 px pane headings, compact 9–13 px table/supporting text, weight and truncation match the dense operational reference.
- Spacing and layout rhythm: 64 px pane headers, 12–16 px control gutters, 42 px filter controls, compact table rows and fixed-height desktop workbench maintain the reference density. The right pane becomes a drawer at narrower viewports.
- Colors and visual tokens: existing `--kairay-red`, `--kairay-yellow`, warm canvas, line and muted tokens map closely to the source's semantic selection and section accents.
- Image quality and assets: the reference contains no raster product imagery. The production logo component was not changed; the lightweight local fixture does not serve its production logo endpoint.
- Copy and content: the user-requested heading copy is removed. Remaining labels are concise Chinese operational terms backed by real order fields.

## Findings

- No actionable P0, P1 or P2 visual differences remain for the requested grouped-customer order workflow.
- Accepted constraint: the reference's lifecycle status filter/chips were not copied because the production order model has no order-fulfillment status. Inventing a status would misrepresent real data.

## Interaction and accessibility checks

- Switching from FLOG to Johan changes the middle table from two orders to one and updates every detail-pane value.
- Searching `August` reduces FLOG to the matching order and updates the detail pane.
- Closing the detail pane expands the center table; the row action reopens it.
- Customer selection, refresh, date inputs, search inputs, row action and download link are keyboard-reachable controls.
- Browser console: no warnings or errors.
- Production TypeScript build: passed.
- Targeted frontend tests: 8 passed.

## Comparison history

1. Initial default-width capture exercised the responsive detail drawer; it was not used for fidelity judgment because it did not match the 1583 × 907 source viewport.
2. The viewport was normalized to 1583 × 907. The three-pane layout, selected customer, selected order and open detail state matched the intended composition with no P0/P1/P2 visual finding.
3. Interaction review found that closing the detail pane immediately reopened it. A separate open/closed state was added; post-fix evidence confirmed close and row-action reopen both work while retaining the same layout.

## Implementation checklist

- [x] Group real orders by customer.
- [x] Filter the table to the active customer.
- [x] Remove the old administrator order heading block.
- [x] Add functional customer search, date range and order search.
- [x] Keep order details and Excel download visible in a right pane.
- [x] Preserve customer-facing `My Orders` and its detail/download flow.
- [x] Verify desktop and responsive states, primary interactions, console and build.

final result: passed
