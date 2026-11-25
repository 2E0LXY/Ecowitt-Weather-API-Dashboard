# Uncommitted edits found on the server (2026-11-25)

Source: /var/www/weather-dashboard on host `2e0lxy`, branch `main` at 62f3592 (2 commits behind origin/main: CI signing and the
ShipProof baseline, neither touches these files). Nothing was applied, deployed or reverted. Canonical copy of the patch (exact
bytes) is on the host: /root/backups/weather-dashboard-uncommitted-*.patch.

Verified 2026-11-25 in a temporary worktree of origin/main: `git apply --check` passes, the patch applies, `python3 -m py_compile
api/app.py` succeeds. No test suite was run. The patch was scanned for secret-like added lines (api key, token, secret, password,
bearer, mac=): none.

| Change | Effect |
|---|---|
| `api/app.py`: verify derived SatDump images exist (HEAD, then 1-byte ranged GET) before listing them | Stops dead image links in the satellite payload |
| `api/app.py`: `/api/satellite-image` returns 404 (not 502) when the source returns 404 | Correct status for a missing image |
| `static/weather.html`: replace the Tailwind CDN script with a local `/weather-tailwind.css` | Removes a runtime CDN dependency |
| `static/weather.html`: add Console Batt reading | New UI field |
| `static/weather.html`: load `/radio-theme.css`, `/weather-approved.css`, `/weather-approved.js`, `/global-nav.js` | **Those assets are not in this repo**; they are served from elsewhere on the host. Confirm where they live before porting. |

Repo copy of the patch has one line (`radio-theme-styles`) without the trailing CR present on the host copy; apply with
`git apply --ignore-whitespace`, or use the host copy.

Also on the host, untracked and not for commit: 13 backup files (`api/app.py.bak.*`, `static/weather.backup-*`, `static/weather.html.bak*`).
Suggest adding `*.bak*` and `*.backup-*` to .gitignore.
