# Resource loading

The public login page loads independently of the authenticated workspace. Account
verification runs once during startup. Administrator, order and quotation pages
load when opened, with a refresh action if a page chunk cannot be downloaded.

The product library renders its first 40 records, then fetches the remaining
250-record batches against the same server snapshot. All records are still loaded
for existing filters, quotations, related sets and complete batch-SKU matching.
This change reduces the initial response size; it does not reduce the total
catalog data downloaded or replace the server's full snapshot aggregation.

Switching between library and quotation views reuses the same loading operation.
A completed library is reused on returning from another view for up to 60 seconds.
Leaving the library cancels an unfinished request, and logging out clears loaded
product data. Card view initially mounts 40 records and reveals more when scrolling
or pressing “Load more products”. List view retains its 20-record pagination.
The first six displayed images are requested eagerly; other thumbnails remain lazy.

## Build budgets

Run these commands from `app/fontend`:

```text
npm run build
npm run check:performance
npm run test:loading
```

The build check follows the entry's static import graph, including shared chunks
and styles. Its budgets are less than 100 KB gzip of initial JavaScript and less
than 45 KB gzip of initial CSS. It also requires separate workspace and page chunks.
These are project budgets, not browser loading-time guarantees.

At the baseline commit `350fbaa`, initial JavaScript was 747.44 KB / 202.66 KB gzip,
and initial CSS was 280.77 KB / 49.62 KB gzip. After this change, the initial
JavaScript is approximately 226.79 KB / 71.12 KB gzip and initial CSS is
231.35 KB / 40.13 KB gzip. Initial JavaScript plus CSS gzip size falls from
252.28 KB to approximately 111.25 KB (56% less).

Local browser checks use 550 fixture products and mock account/API responses.
They verify that the public page requests no workspace/admin/quotation chunks,
startup verifies the session once, the grid mounts 40 cards, complete batch search
can find a SKU in the last data batch, and library/quotation navigation does not
download the library again. Desktop and 390 x 844 login layouts are checked with
the real bundled login images. These checks do not measure production LCP or INP.

The full frontend suite has four pre-existing failures: an outdated admin-order
refresh assertion and three PDF export tests involving Chinese font encoding.
They are present before and after this change. One existing test is skipped.

## Production cache configuration

`ops/frontend-cache.caddy` is a cache-policy snippet for the existing Caddy site
block. It is prepared for deployment and has not been applied to production.
Install it at a reviewed location and import it **inside** the existing
`pr.kairaygolf.com` block, keeping existing authentication and proxy routes:

```caddyfile
import /etc/caddy/frontend-cache.caddy
```

Validate the complete site's Caddy configuration before reloading it. After applying
the policy, verify that a content-hashed `/assets/*.js` or `*.css` response has
`Cache-Control: public, max-age=31536000, immutable`, while `/` and `/index.html`
have `Cache-Control: no-cache`. Private API/media paths and unversioned public
files are excluded. Keep the previous build's hashed assets during a release so
open tabs can still resolve their deferred chunks.

Before accepting production performance, record LCP, INP and CLS for real logged-in
and logged-out visits on desktop and mobile networks. Backend snapshot construction
and network latency still need authenticated production measurements.
