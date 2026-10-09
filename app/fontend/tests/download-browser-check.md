Batch download acceptance:

1. Sign into the deployed asset site in desktop Edge or Chrome.
2. Search for two SKUs (for example `6016558 6016559`), select both, and click Download selected.
3. Choose an empty writable local destination and allow this site's folder access.
4. Both SKUs must remain visible in Downloads. Files should appear in separate product folders with their original names and nested folders. No ZIP or Drive preparation request should occur.
5. Wait for both tasks to say Saved. Check 11 and 19 files respectively for the example above, and compare file sizes with the product details.
6. Repeat a product click while it is queued or active: no extra task or file transfer should start.
7. Stop a task before completion, then Retry remaining files. Already committed files must not be fetched again. A failed task must not block the other product.
8. On an unsupported browser, show explicit individual file links and do not report Saved merely because a download link was exposed.
9. Repeat at 390px wide: controls and task panel must fit without horizontal overflow.

Automated coverage: `npm run test:downloads`. These tests cover the real scheduler and streamed writer with injected network and directory handles; they do not prove that a user's native folder picker works. Keep the site tab open while direct downloads run. A failed individual file restarts from its beginning; retry resumes the set of remaining files rather than byte ranges inside a file.
