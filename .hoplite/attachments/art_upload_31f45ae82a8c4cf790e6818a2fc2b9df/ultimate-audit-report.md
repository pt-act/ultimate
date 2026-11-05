# Ultimate — Comprehensive Audit Report

**Target:** `https://github.com/HazAT/ultimate` @ `c00bea3` (main, pushed 2026-10-31)
**Audited:** 2026-10-31 · static analysis + token-level WCAG computation · **no code modified**
**Scale:** 824 tracked files, 511 `.ts` + 191 `.tsx`, ~140k LOC TS/TSX, 53 extensions, 214 test files

**What Ultimate is:** a local-first coding agent (Pi Durable harness) with a React 19 web UI. A Node HTTP server binds `127.0.0.1`, streams state to the browser over SSE, and runs an AI agent with `read/write/edit/bash/browser` tools inside the user's project directory. Extensions are TypeScript modules loaded server-side through Vite's module graph and execute with full Node privileges in the server process. Projects can ship their own extensions in `.ultimate/extensions/`, gated by a one-time trust decision.

---

## Verdict

**Ship with known risks.** This is a well-engineered codebase with an unusually careful security posture for a local-first app: loopback-only binding, a real origin/identity gate, an explicit consent boundary before project code runs, pnpm 11's supply-chain defaults intact, no obfuscation, no telemetry, and every egress destination explained. I found **no Critical and no High findings**.

The material findings are: **one missing anti-framing header that leaves the UI clickjackable**, **systemic WCAG AA contrast failures driven by opacity-modified text utilities**, **948 fixed-px font sizes that ignore the user's font-size preference**, **no CI of any kind on a 140k-LOC project**, **no idempotency on message submission**, and **no security-disclosure channel**. None of these are remotely exploitable without the user being on the machine.

---

## Findings

### Security

#### S1 — No anti-framing headers; the loopback admission path bypasses the `Sec-Fetch-Dest` check
- **Severity:** Medium
- **Category:** Security
- **Location:** `server/request-security.ts:34-56` (`admit`); `server/main.ts:78-88` (request handler); `web/index.html`
- **Issue:** `admit()` returns `true` for any request whose `Host` is a loopback authority and which carries no `Origin` header — **before** the fetch-metadata checks at lines 47-56. Separately, no response anywhere in the codebase sets `X-Frame-Options` or `Content-Security-Policy: frame-ancestors` (grep across all `.ts`/`.tsx`/`.html`: zero hits). A browser does not send `Origin` on an iframe navigation, so `!origin` is satisfied and the request is admitted before `sec-fetch-dest === 'document'` is ever consulted. The `navigation` relaxation at lines 47-54 (which restricts the relaxation to root document navigations) is therefore dead code on the loopback path.
- **Impact:** Any web page can embed `http://127.0.0.1:4747/` in an iframe and overlay it with attacker-controlled UI. The agent has unrestricted `bash` access to the project directory with no per-command approval, so a user tricked into clicking an overlay that lands on the real Send/Steer control submits attacker-chosen instructions to the agent. Classic clickjacking, no data read-back required (the framed document stays cross-origin to the attacker).
- **Evidence:**
  ```ts
  // server/request-security.ts:39-45
  const { host, origin } = request.headers
  if (
    !proxied(request.headers) &&
    loopbackAuthority(host, port) &&
    (!origin || loopbackOrigin(origin, port))
  )
    return true
  ```
  `server/main.ts:79-83` calls `admit()` then goes straight to `vite.middlewares(request, response)`; no security headers are added on either path.
- **Reproduction:** Serve `http://evil.test/` containing `<iframe src="http://127.0.0.1:4747/" style="position:fixed;inset:0;opacity:0.01;z-index:99999">` plus an overlapping fake "Send" button. Load it in Chrome with Ultimate running. The app renders inside the frame.
- **Recommended fix:** Set `Content-Security-Policy: frame-ancestors 'none'` (and `X-Frame-Options: DENY`) on every response — including the Vite-served HTML and the JSON API — in `server/main.ts`'s handler. Independently, move the `sec-fetch-site`/`sec-fetch-dest` evaluation **above** the loopback early return so the `navigation` carve-out actually applies, and restrict the carve-out to `request.url === '/'`.
- **Confidence:** Confirmed (code path); High Confidence (browser behaviour).

#### S2 — API responses carry no cache, referrer or sniffing directives
- **Severity:** Low
- **Category:** Security
- **Location:** `server/api.ts:80-83` (`reply`)
- **Issue:** `reply()` sets only `Content-Type: application/json`. No `Cache-Control`, `X-Content-Type-Options`, `Referrer-Policy` or `Content-Security-Policy` is set on any API response or on the app HTML. `GET /api/conversations/:id/history` returns a full transcript page.
- **Impact:** (a) Conversation content — potentially proprietary code and secrets pasted into the chat — can be written to the browser's on-disk HTTP cache, readable by another local user or recovered from a disk image. (b) The `/api/...` URLs (which carry conversation ids) are leaked in the `Referer` header to any external link followed from the UI. (c) Absence of `nosniff` is a latent risk if any response's content type were ever ambiguous.
- **Evidence:** `server/api.ts:80-83` — `response.writeHead(status, { 'Content-Type': 'application/json' })`. Repo-wide grep for `X-Frame-Options|frame-ancestors|Content-Security-Policy|X-Content-Type-Options` returns nothing.
- **Reproduction:** `curl -sD- http://127.0.0.1:4747/api/conversations/1/history -o /dev/null` → response headers contain only `Content-Type`. Inspect Chrome's `chrome://net-internals/#events` or the disk cache after loading a conversation.
- **Recommended fix:** In `reply()` and on the HTML response, send `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and a CSP with `default-src 'self'; frame-ancestors 'none'`. This also closes S1 in one place.
- **Confidence:** Confirmed.

#### S3 — The extension-action CSRF guard is inverted and only passes because of `admit()`
- **Severity:** Low
- **Category:** Security
- **Location:** `server/api.ts:127-128`
- **Issue:** The guard reads `if (request.headers['sec-fetch-site'] !== 'same-origin' && !request.headers.origin) throw new HttpError(403, ...)`. It rejects only requests that have **neither** a same-origin `Sec-Fetch-Site` **nor** any `Origin` header. A cross-site request that *does* carry an `Origin` header satisfies the second clause and is therefore **not** rejected here. The protection today comes entirely from `admit()` at `server/api.ts:415-418`.
- **Impact:** Defence-in-depth only, today. If `admit()` is ever relaxed (a plausible future change — the Tailscale path already relaxes fetch metadata for root navigation), this check silently stops being a CSRF guard for every extension action, including the ones that write files and run commands.
- **Evidence:** `server/api.ts:127-128` vs. the intended semantics of a same-origin check. Compare `runAction`'s sibling guards, which are correctly positive (e.g. `server/api.ts:131-132` validates the conversation id).
- **Reproduction:** `curl -H 'Origin: http://evil.test' -H 'Sec-Fetch-Site: cross-site' -X POST http://127.0.0.1:4747/api/extensions/<ext>/actions/<act>` — currently blocked upstream by `admit()`, but this line does not block it.
- **Recommended fix:** Invert to a positive check: require `sec-fetch-site === 'same-origin'`, or (when the header is absent, i.e. a non-browser client) require `Origin` to equal the server's own origin.
- **Confidence:** Confirmed (logic); impact contingent on a future change — High Confidence.

#### S4 — Tailscale identity is trusted from a request header
- **Severity:** Low
- **Category:** Security
- **Location:** `extensions/tailscale/server.ts:282-288`
- **Issue:** Remote access is authorised by reading `headers['tailscale-user-login']` and checking membership of the `tailscale.allow` list. The code assumes Tailscale Serve overwrites any client-supplied value for that header.
- **Impact:** If a deployment ever places another proxy in front of Serve — or if Serve's header-overwrite behaviour differs across versions — a client could assert another user's login and be admitted to the instance over the tailnet. The instance exposes full agent and file access.
- **Evidence:** `verify: ({ headers }) => { const login = headers['tailscale-user-login']; return typeof login === 'string' && allow.includes(login) ? { login } : undefined }`.
- **Reproduction:** Not reproducible against stock Tailscale Serve, which sets this header itself. Requires a modified Serve deployment or a proxy in front of it.
- **Recommended fix:** Treat the header as authoritative only when the request is not proxied by something else, and fail closed if `X-Forwarded-For`/`Forwarded` indicate an unexpected hop count. Document the dependency on Serve's header-overwrite semantics.
- **Confidence:** Needs Verification (depends on Tailscale Serve's documented behaviour, which I did not test).

#### S5 — Action error messages are echoed verbatim to the browser
- **Severity:** Informational
- **Category:** Security
- **Location:** `server/api.ts:151-157`
- **Issue:** A failed action's error message is returned as `{ error: message.slice(0, 500) }`. Filesystem errors carry absolute paths; provider errors may carry fragments of API responses.
- **Impact:** Low. The app is loopback-only, the operator is the intended reader, and the comment states the behaviour is deliberate so a setup problem can explain itself.
- **Evidence:** `server/api.ts:155-157` — "The message is the action author's; the UI shows it".
- **Reproduction:** Trigger an action that touches a missing path; the response body contains the absolute path.
- **Recommended fix:** No change required. If a non-loopback origin is ever enabled, redact absolute paths.
- **Confidence:** Confirmed.

#### S6 — The browser tool can read the local API from any page it visits
- **Severity:** Informational
- **Category:** Security
- **Location:** `extensions/browser/server.ts`
- **Issue:** The browser tool drives a real Chromium at arbitrary URLs. A page it visits can fetch `http://127.0.0.1:4747/api/...` and read the response, because that request is same-origin to the page the browser is on and `admit()` admits loopback requests with no `Origin`.
- **Impact:** A prompt-injected agent could exfiltrate local conversation data through the browser. This is **not an escalation**: the agent already has `bash` in the project directory and can read the same storage directly.
- **Evidence:** `admit()` loopback branch; `extensions/browser/server.ts` navigates to model-supplied URLs.
- **Reproduction:** Ask the agent to browse `http://127.0.0.1:4747/api/conversations` in a page it controls.
- **Recommended fix:** No change required — the browser tool is meant to browse arbitrary URLs, and the data is already reachable. Worth stating explicitly in the threat model so it is not mistaken for a sandbox boundary.
- **Confidence:** Confirmed.

---

### Race Condition & Reliability

#### R1 — No CI of any kind
- **Severity:** Medium
- **Category:** Reliability
- **Location:** `.github/` — contains only `pull_request_template.md`; there is no `.github/workflows/`, and no other CI config (`.circleci`, `.gitlab-ci.yml`, `azure-pipelines.yml`, `buildkite`, `.woodpecker`, `Dockerfile`, devcontainer) anywhere in the tree.
- **Issue:** A 140k-LOC, 824-file project with 214 test files, a custom lint plugin (`lint/ultimate.ts`) and a documented `pnpm check` / `pnpm test` gate has **no automated gate** on pull requests or pushes.
- **Impact:** Nothing runs `pnpm check` or `pnpm test` before a change lands. `AGENTS.md` states "the lander runs every suite" — but the lander is an in-product gate that runs when the agent lands a branch into *this* clone, and `AGENTS.md` separately grants the top-level agent standing permission to "commit verified work, land it and now push the destination branch to `origin` ... without asking". A direct push bypasses the lander entirely. The result is exactly the class of defect a CI gate exists to catch: a regression that only shows up on a machine that is not the author's.
- **Evidence:** `ls .github/workflows` → *No such file or directory*. Repo-wide search for CI config files → zero hits. GitHub API for the repo shows no workflow runs.
- **Reproduction:** Open any pull request on the repository; the checks list is empty.
- **Recommended fix:** Add `.github/workflows/ci.yml` running `pnpm install --frozen-lockfile`, `pnpm check`, `pnpm test`, and `pnpm test:e2e` on Node 26, triggered on `pull_request` and `push` to `main`. Make it a required status check.
- **Confidence:** Confirmed.

#### R2 — Concurrent conversation refresh can overwrite fresher `busy` flags with stale ones
- **Severity:** Medium
- **Category:** Race Condition
- **Location:** `server/api.ts:222-238` versus `server/api.ts:243-262`
- **Issue:** Two writers mutate the module-level `summaries` array. The graph subscriber (lines 243-262) recomputes `busy` for **every** summary and writes `summaries = next`. `refreshConversations` takes a shallow copy at line 223 (`const next = ids ? [...summaries] : []`), recomputes `busy` **only** for the conversation ids it just refreshed, and writes the whole array back at line 236 (`summaries = next`). If the subscriber's 100 ms timer fires between the copy at line 223 and the write at line 236, the write restores the pre-subscriber `busy` value for every conversation that was not in the refreshed id set — precisely the conversations whose `busy` flag had just changed.
- **Impact:** The sidebar can show a conversation as idle while a run is active, or busy after it finished, until the next graph change arrives. For a tool whose primary job is showing what the agent is doing right now, a lying status indicator is more than cosmetic.
- **Evidence:**
  ```ts
  // server/api.ts:222-238
  const next = ids ? [...summaries] : []          // read at T1
  for (const fresh of refreshed) { /* busy recomputed here only */ }
  if (JSON.stringify(next) !== JSON.stringify(summaries)) {
    summaries = next                              // write at T2 — may be stale for non-refreshed ids
  ```
  vs. `server/api.ts:251-259`, which recomputes `busy` for **all** summaries before writing.
- **Reproduction:** Start a run in conversation A and a run in conversation B. Let B's commit refresh fire while A's task graph transitions to busy. Observe the sidebar entry for A flip back to idle.
- **Recommended fix:** Merge instead of replace — build the next list from the *current* `summaries` at write time and recompute `busy` for every entry from the live `graph.value` (as the subscriber does), or funnel both writers through one serialised updater.
- **Confidence:** High Confidence.

#### R3 — Message submission has no server-side idempotency; a lost response yields a duplicate message
- **Severity:** Medium
- **Category:** Race Condition
- **Location:** `server/api.ts:571-652` (`submit`), `web/src/app/composer.tsx:286-322`
- **Issue:** `POST /api/conversations/:id/submit` calls `conversation.submit(...)`, which creates a new durable submission every time. There is no idempotency key, no request id, and no server-side duplicate detection. The client guards with a local `sending` flag (`composer.tsx:287,294,320`), which correctly prevents double-clicks — but the guard is lost when the **response** is lost rather than the request. On failure the composer's catch block restores the draft text from `localStorage` (`composer.tsx:310-318`) and shows an error, so the natural user reaction is to press Send again, producing the same text twice in the transcript.
- **Impact:** Duplicate user messages in the conversation history and a duplicated model turn (two provider calls, two sets of tokens, two sets of side effects). The transcript is durable, so the duplicate persists. The same applies to `POST /api/conversations` (line 531), which creates a new conversation per call.
- **Evidence:** `server/api.ts:626-651` — a fresh `conversation.submit()` per request, answered with `json(202, { submissionId: submission.id })`; nothing consults a prior id. `composer.tsx:306-318` — on failure the draft is restored for a resend.
- **Reproduction:** Throttle the network so the server processes the submit but the response is dropped (DevTools → Network → "Offline" after the request leaves, or use a proxy that swallows the response). The composer shows an error with the text restored; press Send again.
- **Recommended fix:** Generate a client-side `requestId` (UUID) per composed message, send it with the submit, and have the server treat a repeated `requestId` for the same conversation as the same submission (Pi Durable's `submit` already accepts a `requestId` — `extensions/update/server.ts` uses exactly that for its merge request, so the primitive exists).
- **Confidence:** Confirmed for the server-side gap; High Confidence for the client path.

#### R4 — `pnpm install` runs automatically, without asking, when a landing changes the lockfile
- **Severity:** Informational
- **Category:** Reliability / Supply Chain
- **Location:** `extensions/update/server.ts:76-84` (`installPackages`), `:140-158` (`install-landed` reactor)
- **Issue:** When a landing changes `pnpm-lock.yaml` or `patches/`, the update extension runs `pnpm install --frozen-lockfile` in the clone automatically, in the background, without a user prompt.
- **Impact:** Low, because pnpm 11's safe defaults are in force (see SC3): the install is lockfile-frozen, so it installs exactly the pinned versions with verified integrity hashes; dependency build scripts run only for the one package in the `allowBuilds` allowlist (`esbuild`); a package published less than 24 hours ago cannot be resolved at all; and `strictDepBuilds` makes a refused build fail the install loudly. The residual concern is that the install is unattended and can leave the clone in a half-updated state (packages installed, core not yet restarted), which the extension does surface as "install owed".
- **Evidence:** `extensions/update/server.ts:80` — `await exec('pnpm', ['install', '--frozen-lockfile'], { cwd: root, timeout: 10 * 60_000 })`, wired to the `install-landed` reactor with `host.react('install-landed', [SubmissionLanded], …)`.
- **Reproduction:** Land a commit that touches `pnpm-lock.yaml`; watch `pnpm install` start in the clone without any prompt.
- **Recommended fix:** Optional. Gate the automatic install behind the same "restart needed?" prompt the extension already surfaces for the core swap, or at minimum show the package delta as a notice.
- **Confidence:** Confirmed.

#### R5 — `supervisor.log` grows without bound
- **Severity:** Low
- **Category:** Reliability
- **Location:** `bin/dashboard.ts:42-56`; documented in `README.md` ("this file is not automatically rotated")
- **Issue:** Every supervisor and core diagnostic is appended as one JSON line to `<state home>/supervisor.log` with `appendFileSync`, and there is no rotation, size cap, or retention policy.
- **Impact:** A long-lived instance accumulates an unbounded file containing core diagnostics, paths, and error text. On a laptop with limited disk this is a slow leak; the file also survives indefinitely after the app is closed.
- **Evidence:** `bin/dashboard.ts:46-49` — `appendFileSync(logPath, JSON.stringify({ at, level, source, text }) + '\n')`; no size check anywhere in the file.
- **Reproduction:** Run Ultimate for a few days with a noisy extension; `ls -lh ~/.ultimate/projects/*/supervisor.log`.
- **Recommended fix:** Rotate at a size threshold (e.g. 10 MB, keeping one previous generation) or truncate on a successful start.
- **Confidence:** Confirmed.

#### R6 — Subscription ids are silently displaced on duplicate `POST`
- **Severity:** Informational
- **Category:** Race Condition
- **Location:** `server/api.ts:368-372`
- **Issue:** If a client re-POSTs a subscription id that is already open, the server stops the existing subscription and returns `{ ok: true }` without distinguishing the two.
- **Impact:** A client bug that reuses ids silently loses the earlier subscription (its events stop) with a success response. The shipped client increments ids per connection and never reuses them, so this is not reachable in normal operation.
- **Evidence:** `server/api.ts:368-372` — `if (connection.ended || connection.closed.has(sub) || connection.subscriptions.has(sub)) { await stop(); return }`, then `json(200, { ok: true })`.
- **Recommended fix:** Return `409` on a duplicate id rather than silently replacing it.
- **Confidence:** Confirmed.

#### R7 — Clean sweep: the async paths that usually break are handled correctly
- **Severity:** Informational
- **Category:** Reliability
- **Location:** multiple
- **Issue:** None — recorded so the audit is not read as claiming more defects than exist.
- **Evidence:** (a) `web/src/app/composer.tsx:287-321` — `sending` guard on both entry and button, reset in `finally`, draft restored from `localStorage` on failure, and a withdrawn steer re-merged back into the draft if the send then fails. (b) `web/src/sdk/store.ts:286-320` — the EventSource reconnects on drop, resubscribes, and only forces its own retry when `readyState === CLOSED`. (c) `web/src/sdk/hooks.ts:532-556` — `useCopy` clears its timeout on unmount; `useNow` clears its interval. (d) `web/src/sdk/registry.ts:266` — an 8 s readiness deadline is a one-shot timer with no leak. (e) `lib/json-file.ts:41-89` — atomic write via temp-file + `fsync` + `rename`, with a per-path serialisation map for read-modify-write. (f) `server/lock.ts:60-119` — SQLite `BEGIN EXCLUSIVE` lock with an owner sidecar; `alive()` treats `EPERM` as alive; `retireStorageOwner` refuses to signal a pid whose `/proc/<pid>/cmdline` is not `server/main.ts`. (g) All 57 empty `catch {}` blocks in shipped code carry an explanatory comment, enforced by the `ultimate/no-silent-catch` lint rule (`vite.config.ts:47`). (h) `bin/dashboard.ts:6-10` strips VT control characters from child output before logging, so tool output cannot inject terminal escapes into the dashboard.
- **Confidence:** Confirmed.

---

### Accessibility

Contrast ratios below are computed directly from the `oklch` tokens in `web/src/index.css` (converted to linear sRGB, WCAG 2.x relative-luminance formula). The script is included with this report as `contrast.py`.

#### A1 — Focus indicator fails WCAG 2.2 SC 1.4.11 in the light theme, and the ring component alone fails in dark
- **Severity:** Medium
- **Category:** Accessibility
- **Location:** `web/src/index.css:34` (light `--ring`), `:73` (dark `--ring`); `web/src/components/ui/button.tsx:5`
- **Issue:** The focus ring is drawn with `focus-visible:ring-[3px] focus-visible:ring-ring/50`. `--ring` already carries an alpha channel (`oklch(0.55 0.17 300 / 0.55)` light, `oklch(0.74 0.13 300 / 0.5)` dark), and Tailwind's `/50` modifier multiplies it again.
- **Impact:** Keyboard focus is effectively invisible for a large share of the UI. The light theme is a first-class, one-command option (`extensions/theme/web.tsx` — "Toggle light and dark theme"), so this is reachable by any user, not an edge case.
- **Evidence:** Computed contrast against `--background`:

  | Theme | `focus-visible:border-ring` | `focus-visible:ring-ring/50` | Required |
  |---|---|---|---|
  | Light | **1.79:1** | **1.28:1** | 3:1 |
  | Dark | 4.42:1 | **2.71:1** | 3:1 |

  The solid, un-alpha'd ring colour would give 5.02:1 (light) and 7.84:1 (dark) — the alpha stacking is the whole problem.
- **Reproduction:** Switch to the light theme, press Tab through the composer and sidebar. The focus state is a faint violet wash that does not meet 3:1 against the page background.
- **Recommended fix:** Make `--ring` opaque in both themes (keep the alpha only in the shadow/glow usage) and drop the `/50` modifier, or define a separate opaque `--ring-focus` token used for focus indicators. Verify with `axe DevTools` or the APG contrast checker.
- **Confidence:** Confirmed.

#### A2 — Systemic AA contrast failure from opacity-modified text utilities
- **Severity:** Medium
- **Category:** Accessibility
- **Location:** 102 files under `web/src/` and `extensions/` — e.g. `web/src/app/header.tsx`, `extensions/onboarding/panel.tsx`
- **Issue:** The palette defines `--muted-foreground` and `--foreground` at a contrast that passes AA, but the UI then scales them down with opacity modifiers. The counts: `text-muted-foreground/70` ×161, `/60` ×95, `/80` ×34, `/50` ×21, `/40` ×6, `/75` ×1, `text-foreground/90` ×67, `/85` ×53, `/80` ×41, `/75` ×5, `/70` ×5.
- **Impact:** Hundreds of labels, timestamps, counts and status captions are below the 4.5:1 minimum for normal text. Several of the most-used variants are 10–12 px, where the contrast requirement is unchanged.
- **Evidence:** Computed against `--background` / `--card`:

  | Utility | Dark bg | Dark card | Light bg | Light card | Required |
  |---|---|---|---|---|---|
  | `text-muted-foreground` (full) | 5.61:1 | 5.38:1 | 5.75:1 | 5.50:1 | 4.5:1 ✓ |
  | `text-muted-foreground/85` | 4.92:1 | 4.72:1 | **3.36:1** | **3.29:1** | 4.5:1 |
  | `text-muted-foreground/80` | **4.23:1** | **4.07:1** | **2.74:1** | **2.72:1** | 4.5:1 |
  | `text-muted-foreground/70` | **4.23:1** | **4.07:1** | **2.37:1** | **2.34:1** | 4.5:1 |
  | `text-muted-foreground/60` | **3.76:1** | **3.63:1** | **1.98:1** | **1.96:1** | 4.5:1 |
  | `text-muted-foreground/50` | **3.30:1** | **3.19:1** | **1.70:1** | **1.69:1** | 4.5:1 |
  | `text-foreground/70` | 9.21:1 | — | **2.92:1** | — | 4.5:1 |

- **Reproduction:** Switch to the light theme and open the Extensions panel or the command palette; the metadata lines ("source · builtin · last updated", section captions) are barely readable.
- **Recommended fix:** Treat this as a token problem, not 284 individual fixes. Introduce semantic tokens that are *already* at the required contrast for their size (`--text-muted`, `--text-subtle`, `--text-disabled`) and migrate usages in batches; where a lighter tone is genuinely wanted for decoration, use a non-text element or an icon instead of dimmed text.
- **Confidence:** Confirmed.

#### A3 — `text-success`, `text-warning` and `text-note` fail AA in the light theme
- **Severity:** Medium
- **Category:** Accessibility
- **Location:** `web/src/index.css:37-39` (light), `:76-78` (dark); 166 usages (`text-warning` ×111, `text-success` ×55)
- **Issue:** The light-theme semantic colours were tuned for hue, not contrast.
- **Impact:** Status text — the "watching"/"scheduled"/"done" labels in the Automations panel, the interrupted-run markers in the transcript, the JSON-tree warnings — is below AA in light mode. These carry meaning, so this is not merely decorative.
- **Evidence:**

  | Token | Dark bg | Light bg | Required |
  |---|---|---|---|
  | `--success` | 9.30:1 | **4.33:1** | 4.5:1 |
  | `--warning` | 10.68:1 | **3.89:1** | 4.5:1 |
  | `--error` | 6.55:1 | 4.91:1 | 4.5:1 ✓ |
  | `--note` | 11.98:1 | **2.21:1** | 4.5:1 |

  (`--error` on `--card` is 4.70:1 in light — a 0.2 margin, worth re-checking.)
- **Reproduction:** Light theme → Automations panel → the status words are pale.
- **Recommended fix:** Darken the light-theme `--success`/`--warning`/`--note` values until they clear 4.5:1 on both `--background` and `--card` (roughly `L ≤ 0.52` for `--success`, `L ≤ 0.50` for `--warning`), and keep the same hue. Re-run the computation for every token pair as part of `pnpm check`.
- **Confidence:** Confirmed.

#### A4 — Form control boundaries are ~1.4:1 (SC 1.4.11 requires 3:1)
- **Severity:** Medium
- **Category:** Accessibility
- **Location:** `web/src/index.css:33` (light `--input`), `:72` (dark `--input`); e.g. `extensions/automations/form.tsx:241`, `extensions/cloud/join.tsx:95`, `extensions/goal/dialog.tsx:72`
- **Issue:** Text inputs are styled `border border-input` with either `bg-transparent` or `bg-background` — the same colour as the page. The 1 px border is therefore the only visual indication that the control exists.
- **Impact:** Low-vision users may not be able to identify form fields at all, in either theme.
- **Evidence:** `--input` vs `--background` = **1.47:1** (light), **1.38:1** (dark); `--input` vs `--card` = 1.40:1 / 1.33:1. Required: 3:1 for the boundary of a user-interface component (WCAG 1.4.11 Non-text Contrast).
- **Reproduction:** Inspect any form in the Automations or Cloud panels at 200% zoom; the field edges nearly vanish against the card.
- **Recommended fix:** Darken `--input` to reach ≥3:1 against both `--background` and `--card` (approximately `oklch(0.72 0.01 270)` light, `oklch(0.42 0.008 270)` dark), or give inputs a distinct surface fill so the control is identifiable without relying on the border.
- **Confidence:** Confirmed.

#### A5 — 948 fixed-px font sizes; the UI does not respond to the user's font-size preference
- **Severity:** Medium
- **Category:** Accessibility
- **Location:** 119 files across `web/src/` and `extensions/` — `text-[11px]` ×279, `text-[12px]` ×190, `text-[13px]` ×115, `text-[11.5px]` ×115, `text-[10.5px]` ×103, `text-[12.5px]` ×73, `text-[10px]` ×48, down to `text-[8.5px]` ×1
- **Issue:** Typography is locked to absolute pixels. `web/src/index.css:209` also pins the body to `font-size: 14px`. Neither responds to the browser's default-font-size or minimum-font-size settings.
- **Impact:** Users who have raised their system or browser font size get the same 8.5–13 px text — below any readable minimum, and outside the intent of WCAG 1.4.4 (Resize Text). `text-[8.5px]` and `text-[9.5px]` are unreadable even at default settings. The fixed-height controls (`h-8`, `size-7`, `h-9`) will also clip when the WCAG 1.4.12 text-spacing overrides are applied.
- **Evidence:** `grep -rhoE "text-\[[0-9.]+px\]" web/src/ extensions/ --include=*.tsx | wc -l` → **948** across **119** files. `web/src/index.css:209` — `font-size: 14px;`.
- **Reproduction:** In Chrome → Settings → Appearance → Font size → 24px, or in Firefox → Settings → Fonts → Minimum font size 24, and reload the app. Nothing changes size.
- **Recommended fix:** Move the type scale to `rem` (the Tailwind `text-xs`/`text-sm` scale already is), keep a small set of `rem`-based density steps for the dense chrome, and replace the fixed-px utilities with those. Where a sub-12 px label is intentional, raise it and re-check the layout rather than shrinking the type. Add a `prefers-reduced-motion` / text-spacing smoke test.
- **Confidence:** Confirmed for the px lock and the user-preference failure; Needs Verification for the 1.4.12 clipping (requires a manual text-spacing-override test).

#### A6 — Decorative icons are not hidden from assistive technology
- **Severity:** Low
- **Category:** Accessibility
- **Location:** all `lucide-react` icon usages, e.g. `web/src/components/ai/prompt-input.tsx:78`, `web/src/components/ui/dialog.tsx:69`
- **Issue:** `lucide-react` renders a bare `<svg>` with no `role="presentation"` / `aria-hidden="true"`. Inline SVGs without an explicit role are exposed to some screen readers as graphics, so a button may be announced as "graphic, Send" or similar.
- **Impact:** Verbose announcements; inconsistent across screen-reader/browser combinations. All icon-only buttons do carry a correct `aria-label` (verified across all 11 `size="icon*"` usages), so this is noise rather than a missing name.
- **Evidence:** All 11 icon-only `<Button size="icon*">` usages inspected (`web/src/app/header.tsx:46`, `web/src/app/titlebar.tsx:304`, `web/src/components/ai/conversation.tsx:68`, `web/src/components/ai/prompt-input.tsx:74`, `extensions/automations/panel.tsx:508`, `extensions/cloud/join.tsx:152`, `extensions/lineage/web.tsx:425`, `extensions/models/login.tsx:299`, `extensions/onboarding/survey.tsx:75`, `extensions/secrets/web.tsx:158`, `extensions/subagents/definitions.tsx:357`) — all have `aria-label` or an accessible-name-bearing child.
- **Reproduction:** Turn on a screen reader and navigate the composer; the arrow icon inside the Send button is announced in addition to the button name.
- **Recommended fix:** Add `aria-hidden="true"` to decorative SVGs — simplest as a global wrapper, or by configuring the icon factory if the app exposes one.
- **Confidence:** High Confidence.

#### A7 — Clean sweep: the accessibility fundamentals are in place
- **Severity:** Informational
- **Category:** Accessibility
- **Location:** `web/src/components/ui/`, `web/src/components/ai/conversation.tsx`
- **Issue:** None.
- **Evidence:** (a) `web/src/components/ui/dialog.tsx` uses Radix `DialogPrimitive.Content` → focus trap, `Esc` to close, focus restoration, `aria-modal` and `DialogTitle`/`DialogDescription` wiring all come from the primitive. (b) Zero `<img>` elements without `alt`; zero `onClick` handlers on non-interactive elements (`div`/`span`/`li`/`p`). (c) `role="log"` on the transcript (`web/src/components/ai/conversation.tsx:15`) gives streaming content an implicit polite live region. (d) `prefers-reduced-motion: reduce` globally disables animations and transitions (`web/src/index.css:223-230`). (e) `font-size: 16px` on `input`/`textarea`/`select` under `@media (pointer: coarse)` prevents iOS focus-zoom (`web/src/index.css:234-240`). (f) `@media (pointer: coarse)` plus `pointer-coarse:size-9` on the header buttons keeps touch targets ≥24 px; the smallest token, `size-6`/`icon-xs`, is exactly the 24 px WCAG 2.2 minimum. (g) Token discipline is otherwise excellent — only **3** hard-coded hex colours exist in the entire UI (`#7b47bf`, `#e4d6ff`, `#bb9af4`, all in the splash logo), everything else is a token.
- **Confidence:** Confirmed.

---

### Visual Consistency

#### V1 — Two divergent "destructive" colours in the same token set
- **Severity:** Low
- **Category:** Visual Consistency
- **Location:** `web/src/index.css:31,40` (light `--destructive`, `--error`), `:70,79` (dark)
- **Issue:** `--destructive` and `--error` are two separate tokens with identical values in light (`oklch(0.56 0.19 25)`) and near-identical values in dark (`0.66 0.18 25` vs `0.7 0.17 25`). They are used for different things — `--destructive` as a button fill, `--error` as error text — so the same semantic event can render in two slightly different reds depending on which role it fills.
- **Impact:** Low visual drift; mostly a maintenance hazard (a fix to one does not reach the other).
- **Evidence:** `web/src/index.css:31` vs `:40`; `:70` vs `:79`.
- **Recommended fix:** Derive `--error` from `--destructive` (`--error: var(--destructive)`) or document the intended difference explicitly.
- **Confidence:** Confirmed.

#### V2 — Density steps are expressed as arbitrary values rather than a scale
- **Severity:** Low
- **Category:** Visual Consistency
- **Location:** 119 files (same set as A5)
- **Issue:** The type scale is `{8.5, 9.5, 10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14, 14, 15, 17, 19, 22}px` — sixteen distinct sizes in half-pixel steps, applied ad hoc per component.
- **Impact:** Two components authored by different hands drift by half a pixel; a future change to the density model cannot be made centrally, and the half-pixel steps hint at sub-pixel layout tuning that will not survive a font change.
- **Evidence:** `grep -rhoE "text-\[[0-9.]+px\]" … | sort | uniq -c` → 16 distinct values; `text-[11px]` alone appears 279 times.
- **Recommended fix:** Define five or six named density steps (`--text-xs` … `--text-lg`) and migrate. This is the same work as A5 and should be done together.
- **Confidence:** Confirmed.

#### V3 — Clean sweep: interaction states and copy are consistent
- **Severity:** Informational
- **Category:** Visual Consistency
- **Location:** `web/src/components/ui/`, `web/src/app/`
- **Issue:** None material.
- **Evidence:** The button primitive (`web/src/components/ui/button.tsx`) carries a uniform state matrix — `hover`, `focus-visible` (ring + border), `disabled:pointer-events-none disabled:opacity-50`, `aria-invalid:border-destructive aria-invalid:ring-destructive/20` — and every variant uses the same token set. Radii come from `--radius-sm/md/lg/xl`; shadows from `shadow-xs`/`shadow-md`/`shadow-lg`; the spacing scale is Tailwind's. The `MessageResponse` memo (`web/src/components/ai/message.tsx:139-141`) compares `children` and `isAnimating`, so streaming re-renders are bounded. No `text-muted-foreground` colour is used as the sole carrier of meaning — status is always paired with an icon or a word (`extensions/automations/parts.tsx:134-135` maps state to both a dot and a word).
- **Confidence:** Confirmed.

---

### Supply Chain

#### SC1 — No release artifacts, no checksums, no signatures, no SBOM
- **Severity:** Medium
- **Category:** Supply Chain
- **Location:** repository-wide; GitHub API for `releases` and `tags` returns empty arrays
- **Issue:** The project publishes **no releases and no tags** (verified against the GitHub API: `releases: []`, `tags: []`). There is therefore no artifact to checksum or sign, and no SBOM. Installation is `git clone` + `pnpm install` + `pnpm link --global`, which means the operator's trust anchor is the Git remote and the npm registry.
- **Impact:** There is no out-of-band way to verify what the operator is running. A compromised GitHub account or a force-pushed `main` (which `AGENTS.md` explicitly authorises the agent to do) delivers new code with no signature to check and no published checksum to compare against. The dependency layer is protected by pnpm's lockfile integrity hashes; the *application* layer is not.
- **Evidence:** `curl https://api.github.com/repos/HazAT/ultimate/releases` → `[]`; `/tags` → `[]`; `git tag | wc -l` → 0. `README.md` documents only the clone-and-install path. `package.json` has no `publishConfig`; the package is `"private": true`.
- **Reproduction:** `git ls-remote --tags https://github.com/HazAT/ultimate` → empty.
- **Recommended fix:** Publish tagged releases with a `SHA256SUMS.txt` and a detached signature, and add a `SECURITY.md` with a disclosure address (see SC4). At minimum, document the exact `git rev-parse HEAD` a given installation is running and how to verify it against the remote.
- **Confidence:** Confirmed.

#### SC2 — The auto-updater applies upstream commits without signature verification
- **Severity:** Low
- **Category:** Supply Chain
- **Location:** `extensions/update/server.ts:196-205` (`fastForward`), `:264-282` (`run`), `extensions/update/clone.ts:48-63` (`fetchIfDue`)
- **Issue:** The update extension fetches `origin` at most hourly (5-minute tick, hourly fetch ceiling) and fast-forwards the clone to `origin/<branch>` on request. Git's default transport verifies the SHA-1/SHA-2 object hashes but **not** commit signatures; `git verify-commit` is never called, and no `gpg.format`/`commit.gpgsign` requirement is enforced. The fetched code is then installed and executed.
- **Impact:** Anyone who can write to `origin` — a compromised maintainer account, a leaked deploy key, a hijacked CI — lands code that runs on the operator's machine on the next update. The lockfile pins *dependencies*, not the application code.
- **Evidence:** `extensions/update/clone.ts:56` — `fetchOrigin(git)`; `extensions/update/server.ts:200` — `fastForward(git, undefined, () => landing(host))`. Repo-wide grep for `verify-commit`, `gpgsign`, `gpg` → no hits.
- **Reproduction:** `git -C <clone> log --show-signature -1` after an update — no signature data.
- **Recommended fix:** Require signed commits on `main` (`git config --global commit.gpgsign true` is not enough — enforce it in a `pre-receive` hook) and verify with `git verify-commit` before fast-forwarding, or at minimum pin updates to a reviewed tag rather than a branch head. Document the trust model for `origin`.
- **Confidence:** Confirmed.

#### SC3 — pnpm 11's supply-chain defaults are in force; the build-script allowlist has one stale placeholder
- **Severity:** Low
- **Category:** Supply Chain
- **Location:** `pnpm-workspace.yaml:1-5` (`allowBuilds`); `package.json` `packageManager: "pnpm@11.8.0"`
- **Issue:** The project pins **pnpm 11**, whose safe defaults are on by default and which this project inherits: `minimumReleaseAge` = **1440 minutes** (a newly published package version cannot be resolved for 24 hours — the window in which a compromised release is most likely to be detected and unpublished), `blockExoticSubdeps` = `true` (blocks non-registry git/tarball *sub*dependencies), and `strictDepBuilds` = `true` (an install **fails** rather than silently skipping a dependency's build script). Dependency build scripts are therefore blocked by default, and `allowBuilds` is the explicit allowlist: `esbuild: true` (it genuinely needs to place a native binary), `@google/genai: false`, `protobufjs: false`.
  The defect is the fourth entry: `workerd: set this to true or false` is **pnpm's auto-generated placeholder**, left unresolved in a committed file. `workerd` does not appear anywhere in `pnpm-lock.yaml` (0 matches), so it is a stale artifact of an auto-populated config.
- **Impact:** No effect on installs today — `workerd` is not in the dependency tree. Three residual risks: (a) it misleads a reader into believing `workerd` is a dependency that builds; (b) per pnpm's own documentation, a placeholder "behaves like a missing entry: builds are skipped and `strictDepBuilds` still fails", so if `workerd` were ever added to the tree, its build script would be skipped **and the install would fail**; (c) any tool that parses `pnpm-workspace.yaml` against pnpm's boolean schema throws `SchemaError: Expected boolean` — a failure mode another project hit in production and had to add a CI test for. Nothing in this repository parses the file today.
- **Evidence:** `pnpm-workspace.yaml:5` — `workerd: set this to true or false`. `grep -c workerd pnpm-lock.yaml` → `0`. `grep -n "  esbuild@" pnpm-lock.yaml` → `esbuild@0.28.2` present (so the `true` is needed); `protobufjs@7.6.6` present (so `false` is correct). pnpm's documented placeholder semantics and `approve-builds` behaviour confirm the interpretation.
- **Reproduction:** `grep workerd pnpm-workspace.yaml pnpm-lock.yaml` → one hit, in the workspace file only.
- **Recommended fix:** Delete the `workerd` line (or set `workerd: false`). Add a CI assertion that every `allowBuilds` value parses as a boolean and that every key names a package present in the lockfile — the exact check another project added after this class of bug bit them.
- **Confidence:** Confirmed.

#### SC4 — No security-disclosure channel; the contribution guide tells reporters not to expect replies
- **Severity:** Medium
- **Category:** Supply Chain
- **Location:** repository root (no `SECURITY.md`); `CONTRIBUTING.md:29-31`
- **Issue:** There is no `SECURITY.md`, and `CONTRIBUTING.md` states *"Issues are not reviewed. Please don't expect a reply."* The GitHub API reports `security_and_analysis: null` (no enabled security features) and `has_issues: true`.
- **Impact:** A researcher who finds a vulnerability in a 140k-LOC agent that executes code on the operator's machine has **nowhere private to report it**. The only channel is a public issue, which the project explicitly does not read — and the sole maintainer would be the only possible recipient anyway.
- **Evidence:** `ls SECURITY.md` → not found; `curl .../repos/HazAT/ultimate | jq .security_and_analysis` → `null`; `CONTRIBUTING.md:29` — "Issues are not reviewed."
- **Recommended fix:** Add `SECURITY.md` naming a private contact (e.g. `security@…` or GitHub's private vulnerability reporting), with a response-time expectation. Enable GitHub private vulnerability reporting. The project's own `SECURITY.md` scope section (as used by the author's other repository) is a good model: name in-scope and out-of-scope areas.
- **Confidence:** Confirmed.

#### SC5 — Machine setup installs a persistent service
- **Severity:** Informational
- **Category:** Supply Chain
- **Location:** `scripts/setup-machine.ts` (whole file); `package.json` `scripts.setup:machine`
- **Issue:** `pnpm setup:machine` writes a systemd **user** unit (`~/.config/systemd/user/ultimate.service`, `WantedBy=default.target`, `Restart=on-failure`) or a macOS launchd agent (`~/Library/LaunchAgents/com.ultimate.app.plist`, `RunAtLoad`, `KeepAlive` on failure), and on Linux enables **linger** for the user (`loginctl enable-linger`), so it starts at boot without a login. This is persistence beyond PATH/env setup.
- **Impact:** The service starts Ultimate unattended with the user's full privileges and keeps running after logout. It is entirely opt-in (an explicit `pnpm setup:machine` invocation, documented in `extensions/cloud/README.md`), fully reversible, and downloads nothing.
- **Evidence:** `scripts/setup-machine.ts:37-56` (unit template, `WantedBy=default.target`), `:192-236` (launchd plist, `RunAtLoad`), `:369-374` (`loginctl enable-linger`). The script downloads and executes **nothing** — every external call is `execFileSync('systemctl'|'launchctl'|'loginctl', [...])` with argument arrays, never a shell string.
- **Reproduction:** `pnpm setup:machine --dry-run` prints the exact unit and agent files without writing them.
- **Recommended fix:** No change required. Document the removal command (`systemctl --user disable --now ultimate.service` / `launchctl bootout gui/$UID/com.ultimate.app`) in the same place the setup is documented, and state the linger implication.
- **Confidence:** Confirmed.

#### SC6 — Tailscale Serve mapping persists beyond the session (opt-in, self-cleaning)
- **Severity:** Informational
- **Category:** Supply Chain
- **Location:** `extensions/tailscale/server.ts:246-256`
- **Issue:** The tailscale extension runs `tailscale serve --bg --yes --https=<port> http://127.0.0.1:<port>`, creating a system-level Serve mapping that survives the Ultimate process. It is removed on `host.onClose` (lines 293-317) and on the next start if the mapping is missing.
- **Impact:** While enabled, the instance is reachable over the tailnet at an HTTPS origin. The extension is in `defaultOff` (`shared/extension-api.ts`), so it never runs unless the user turns it on, and the allow-list defaults to the owner's own login.
- **Evidence:** `extensions/tailscale/server.ts:250-256`; the extension is listed in `shared/extension-api.ts` `defaultOff`.
- **Reproduction:** `tailscale serve status` while the extension is enabled.
- **Recommended fix:** No change required. Consider surfacing a persistent notice while a Serve mapping is active so the user knows the instance is reachable off-machine.
- **Confidence:** Confirmed.

#### SC7 — The one non-registry dependency is properly pinned
- **Severity:** Informational
- **Category:** Supply Chain
- **Location:** `package.json:27`; `pnpm-lock.yaml:26-27,245-246`
- **Issue:** `@earendil-works/pi-claude-code` is installed from `github:earendil-works/pi-claude-code#70abb65186592ca788b29b3db22c3160d629c41f` — a GitHub tarball rather than an npm release.
- **Impact:** A Git dependency bypasses npm's publish pipeline and any registry-side immutability guarantee. Here that risk is well managed.
- **Evidence:** The specifier pins a **full 40-character commit SHA**; the lockfile records `integrity: sha512-7Saq3prm7HBqe4gEkJBcz7UcL4q7nATlItY5OQuwKWZeEgb0AZfDyphoM78C7C3SG+hT0s5APOXA98T4CkAmBw==` for the tarball; pnpm verifies that hash on install. The commit SHA is immutable, so the content cannot change under a fixed specifier.
- **Reproduction:** `grep 'pi-claude-code' pnpm-lock.yaml` — the resolution and its integrity hash.
- **Recommended fix:** No change required. Keep the SHA pin and never relax it to a branch or tag.
- **Confidence:** Confirmed.

#### SC8 — The three dependency patches are functional, not malicious
- **Severity:** Informational
- **Category:** Supply Chain
- **Location:** `patches/@earendil-works__chord@1.4.0.patch`, `…__pi-claude-code@0.1.0.patch`, `…__pi-durable@1.4.0.patch`
- **Issue:** Patched dependencies are a place where malice would hide, so each patch was read end-to-end.
- **Impact:** None found.
- **Evidence:** (a) The `chord` patch replaces a control-character stripper with a fuller ANSI/OSC consumer — it *tightens* sanitisation. (b) The `pi-claude-code` patch adds cache-breakpoint handling, tool-id normalisation (`anthropicToolId`, hashing ids that other providers use), and a `parseStreamingJson` call. (c) The `pi-durable` patch adds a `beforeInput` hook, a `hold()`/`release()` scheduler gate, and a `thinkingLevel` on the response. No patch adds a network call, reads a file outside the project, spawns a process, or alters credential handling.
  - **One observation worth recording:** the `pi-claude-code` patch *removes* the check that rejected tool calls whose names were outside Pi's current tool inventory ("Claude Code returned a tool outside Pi's current tool inventory"), replacing it with a best-effort name mapping. That widens what a Claude Code response may name; a mistranslated name now surfaces as a "tool not available" error to the model rather than failing the turn. Low risk, but it is a deliberate weakening of a validation.
- **Recommended fix:** Keep the patches under review; re-read them whenever the upstream version moves.
- **Confidence:** Confirmed.

---

### Malicious Code

#### M1 — No malicious code found
- **Severity:** Informational
- **Category:** Malicious Code
- **Location:** repository-wide
- **Issue:** None.
- **Impact:** Nothing in the shipped code harms, surveils, or exfiltrates by design.
- **Evidence:** (a) **No obfuscation.** Repo-wide grep for `eval(`, `new Function(`, base64 decoding, hex blobs and charcode tricks returns only three legitimate hits: `Buffer.from(encoded, 'base64')` in the image-validation path (`server/api.ts:605-608`), base64 audio decoding in the voice extension (`extensions/voice/server.ts:93`), and a base64 detector in the codemode summariser (`extensions/codemode/summary.ts:86`). There is no minified or vendored blob in the source tree (the only third-party vendored file is `web/src/components/ai/LICENSE`, which is Streamdown's Apache licence). (b) **No telemetry, analytics, beacon or pixel.** No shipped code contacts a tracking endpoint; the only "reach" style code is `extensions/update`, which fetches the project's own `origin`. (c) **No credential access outside the tool's own configuration.** The secret store (`lib/secrets.ts`) reads only `~/.ultimate/secrets.json`, opens it with `O_NOFOLLOW`, and refuses to read it if the mode has group/other bits. `~/.pi/agent/auth.json` is handled by Pi, not by this repo. (d) **No persistence beyond the documented, opt-in service install** (SC5, SC6). (e) **No profile-file modification** — `setup-machine.ts` writes only a systemd unit or a launchd plist; it never touches `.zshrc`, `.bashrc`, `.profile` or `PATH` environment files. (f) **No hidden network destinations** — see the egress table below; every destination is accounted for and explained.
- **Recommended fix:** No change required.
- **Confidence:** Confirmed.

---

## Egress accounting

Every network destination the **shipped code** contacts (code only — docs, tests and fixtures excluded). Verified by grepping all `fetch(`, `exec`, and URL literals in non-test sources.

| Destination | Purpose | When triggered | Operator opt-out | Verified |
|---|---|---|---|---|
| Model provider APIs (`api.anthropic.com` and others via Pi) | The agent's own inference | Every model call | Yes — choose a provider/login in the UI | Via Pi (`@earendil-works/pi-ai`); not in this repo's source |
| `api.openai.com/v1/audio/transcriptions` | Voice input transcription | When the user records voice input | Yes — extension off / no `OPENAI_API_KEY` secret | `extensions/voice/server.ts:47` |
| `api.openai.com/v1/live/sessions` | Live voice session token | When the user starts live voice | Yes — `voice-live` is in `defaultOff` | `extensions/voice-live/server.ts:447` |
| `api.parallel.ai/v1/{search,extract}` | Web search / page extraction | When the agent uses the parallel tool | Yes — `parallel` is in `defaultOff`; needs an API key | `extensions/parallel/client.ts:1,72` |
| `api.typesafe.ai`, `console.typesafe.ai` | Local/self-hosted LLM provider | When the user configures a Typesafe provider | Yes — provider not configured = unused | `extensions/classify/server.ts:35` |
| `<user's git origin>` (e.g. `github.com/HazAT/ultimate`) | Update check: `git fetch origin` | Every 5 min tick, fetch capped at hourly | Yes — the extension reports state and asks before applying; fetch can be paused | `extensions/update/clone.ts:48-63` |
| `github.com` (HTML only) | "Compare on GitHub" links rendered in the UI | User clicks the link | n/a — a link, not a call | `lib/compare.ts`, `extensions/lineage/web.tsx` |
| `diffshub.com` | "Compare on DiffsHub" links rendered in the UI | User clicks the link | n/a — a link, not a call | `lib/compare.ts:3` |
| `tailscale.com` / `login.tailscale.com` | Tailscale status/login (via the `tailscale` CLI) | Only when the tailscale extension is enabled | Yes — `defaultOff` | `extensions/tailscale/server.ts:150-190` |
| `<user's cloud URL>` (`settings.cloud.url`) | Cloud backup register/sync | When the user joins a cloud | Yes — cloud is off until configured | `extensions/cloud/join.ts:63`, `extensions/cloud/snapshot.ts:298` |
| `<other Ultimate instance>` | Instance-to-instance actions and messages | When the agent talks to another project | Yes — `remotes` in user settings only | `lib/remote.ts:157` |
| `api.tailscale`-style local proxy | n/a | — | — | — |

**No destination is unexplained.** Every entry maps to a user-visible feature with a credential or an explicit configuration, and every optional one is either off by default (`defaultOff` in `shared/extension-api.ts`: `cloud`, `parallel`, `tailscale`, `health`, `classify`, `phase`, `sounds`, `voice-live`) or requires the user to supply a key. There is **no telemetry, no analytics, no crash reporting and no phone-home**.

---

## Installer / bootstrap read-audit

| Script | What it does | Downloads? | Verifies? | Verdict |
|---|---|---|---|---|
| `README.md` "Start" (operator prompt) | Clone, `pnpm install`, `pnpm link --global`, `pnpm start` | Yes — git clone + npm registry | pnpm lockfile integrity hashes | Sound |
| `scripts/setup-machine.ts` | Writes a systemd user unit or launchd plist; `systemctl --user enable --now`; `loginctl enable-linger` | **No** | n/a | Sound; opt-in, reversible, no shell interpolation (`execFileSync` with argument arrays) |
| `scripts/reset.ts` / `scripts/restore.ts` | Move/restore the state home | No | n/a | Sound |
| `scripts/deps.ts` | Prints the extension dependency graph; fails on a cycle | No | n/a | Sound |
| `bin/ultimate.ts` | Supervisor: acquires the project lock, forks the core, proxies TCP, restarts on crash | No | n/a | Sound |
| `extensions/update` | `git fetch origin` + fast-forward + `pnpm install --frozen-lockfile` | Yes — git objects + npm packages | git object hashes only (**not** commit signatures — SC2); pnpm integrity hashes ✓ | See SC2 |

**There is no installer that downloads an unverified binary.** The project's install path is `git clone` + `pnpm install`, so there is no curl-to-shell step to trust.

---

## Obfuscation hits

| Hit | Location | Verdict |
|---|---|---|
| `Buffer.from(encoded, 'base64')` | `server/api.ts:605-608` | Legitimate — validating that a client-supplied image is canonical base64 before accepting it |
| `Buffer.from(audio, 'base64')` | `extensions/voice/server.ts:93` | Legitimate — decoding a browser recording |
| base64 substring heuristic | `extensions/codemode/summary.ts:86` | Legitimate — detecting a base64 run in text for redaction |
| `dangerouslySetInnerHTML` | `web/src/components/ai/ansi-output.tsx:16` | Legitimate — `ansi_up` with `parser.escape_html = true`, and the input is first filtered to numeric SGR sequences only (`web/src/components/ai/ansi-output.tsx:4-12`). `ansi_up` is pinned to 6.0.6, past the 5.0.1 fix for CVE-2021-28861 |
| `frame.innerHTML = resume.html` | `web/index.html:50` | Legitimate today — `resume.html` is the app's own DOM snapshot serialised to `sessionStorage` (`web/src/sdk/resume.ts:51-80`); React escapes all text, and the only `dangerouslySetInnerHTML` in the codebase escapes its input. **Hardening note:** if a raw-HTML rendering path is ever added, this becomes stored XSS. Prefer a `DOMParser` + `importNode` reconstruction over `innerHTML` |
| `eval(` / `new Function(` | — | **Zero hits** |

---

## Persistence findings

| Mechanism | Present? | Opt-in? | Cleanup? |
|---|---|---|---|
| systemd user unit (`ultimate.service`) | Yes — `scripts/setup-machine.ts:37-56` | Yes (`pnpm setup:machine`) | `systemctl --user disable --now ultimate.service` |
| launchd agent (`com.ultimate.app`) | Yes — `scripts/setup-machine.ts:192-236` | Yes | `launchctl bootout gui/$UID/com.ultimate.app` |
| `loginctl enable-linger` | Yes — `scripts/setup-machine.ts:374` | Implied by the above | `loginctl disable-linger <user>` |
| cron / schtasks / systemd timers | **No** | — | — |
| Shell profile edits (`.zshrc`, `.bashrc`, `.profile`) | **No** | — | — |
| `PATH`/env file modification | **No** — the unit carries `Environment=PATH=…` inside the unit file only | — | — |
| Tailscale Serve mapping | Yes — `extensions/tailscale/server.ts:250-256` | Yes (extension is `defaultOff`) | Removed on extension close (`extensions/tailscale/server.ts:293-317`) |
| Registry writes / login items | **No** | — | — |

---

## Dependency provenance

- **`packageManager: "pnpm@11.8.0"`** is pinned, so pnpm 11's supply-chain defaults apply: `minimumReleaseAge` 1440 min, `blockExoticSubdeps` true, `strictDepBuilds` true, and dependency build scripts blocked outside `allowBuilds`.
- All registry dependencies are pinned to **exact versions** in `package.json` (e.g. `"react": "19.3.0"`, `"vite-plus": "1.4.0"`) — no `^` or `~` ranges except `ogl: "^1.0.11"`.
- `pnpm-lock.yaml` (lockfileVersion 9.0) records an `integrity` hash for every resolved package; pnpm verifies each on install.
- `allowBuilds` (`pnpm-workspace.yaml:1-5`) is an explicit build-script allowlist: only `esbuild` is allowed. One entry is a stale pnpm placeholder (SC3).
- `minimumReleaseAgeExclude` (`pnpm-workspace.yaml:6-24`) correctly exempts the `@earendil-works/*` packages and the per-platform `vite-plus` binaries — packages that are published per-platform and needed immediately — from the 24-hour cooldown. This is deliberate, minimal, and exactly right.
- **One** non-registry dependency: the GitHub tarball at SC7 — pinned to a full commit SHA with a recorded integrity hash. `blockExoticSubdeps` does not apply because it is a *direct* dependency, not a transitive one.
- `overrides: { vite: 8.3.5 }` — a single transitive override, pinned. The workspace file documents why: a Dependabot advisory (GHSA-587h-7wmj-h5pm) that `@tailwindcss/vite` and `@vitejs/plugin-react` each resolve `vite` 8.3.1 on their own.
- `patchedDependencies` — three entries, each reviewed at SC8, each with a comment in `pnpm-workspace.yaml` explaining the upstream change to wait for.
- `pnpm-workspace.yaml` also carries the patch provenance comments and the patch-removal criteria, so the upgrade path is documented in the place pnpm will read it.
- **No SBOM, no checksums, no signatures** are published (SC1).

---

## Clean sweep

Verified sound — checked and found **no** issue:

- **Binding and network exposure.** The HTTP server binds `127.0.0.1` explicitly (`server/main.ts:185`); the supervisor's TCP proxy also binds `127.0.0.1` (`bin/ultimate.ts:192`). There is no `0.0.0.0` anywhere.
- **The origin/identity gate.** `admit()` (`server/request-security.ts:34-68`) is called on every request, twice (once in `server/main.ts:78`, once in `server/api.ts:415-418`). It rejects requests carrying proxy headers (`proxied()`, line 109) so a spoofed `X-Forwarded-For` cannot fake a direct connection, validates the Host as a genuine loopback authority including the port and rejecting embedded credentials (`loopbackAuthority()`, line 115), and requires a rule's `verify()` to return a login for remote origins. A failing identity provider fails closed (`catch {}` at line 62, and the rule is re-checked with `rules.has(rule)` at line 60 to close a TOCTOU window).
- **CSRF for state-changing requests.** Cross-site POSTs are rejected by the `Sec-Fetch-Site` check (`server/request-security.ts:56`); a cross-origin `Origin` also fails the loopback branch. Extension actions add a second check (S3) and an `AbortController` tied to the response (`server/api.ts:133-137`).
- **Request-body limits.** `body()` (`server/api.ts:46-63`) caps at 1 MiB, 12 MiB for submissions and actions, rejects non-objects and non-arrays, and validates the parsed shape.
- **Input validation at the boundary.** Conversation ids are validated with `Number.isSafeInteger` and `> 0` in every handler (`server/api.ts:131-132, 400-404, 452-464`); the image path validates MIME type against an allowlist, base64 canonicality, and the 2 MiB cap (`server/api.ts:593-609`); UI-state keys are restricted to `^[A-Za-z0-9_.:-]+$` with a 200-char cap and a 256 KiB total-size cap (`server/api.ts:68-69, 498-513`); the `UI_REVISION` key is reserved against client writes (`server/api.ts:505-506`).
- **Path traversal.** No handler accepts a caller-supplied filesystem path. The one path-shaped parameter — `cwd` on `POST /api/conversations` (`server/api.ts:532`) — is a string the server passes to the harness, and the file tools are Pi's, which enforce the outside-CWD rule; `screenshotFile` (`extensions/browser/server.ts:51-58`) resolves against the conversation cwd and requires a `.png` suffix.
- **Command injection.** The bash tool is Pi's. The only shell built by this repo is the Git-hook installer (`extensions/coding-tools/server.ts:66-80`), which interpolates only `api.conversationId` — a number — and passes every other value through `git rev-parse` inside the command itself. `exec` (`lib/exec.ts`) is called with argument arrays, never a shell string; `scripts/setup-machine.ts` uses `execFileSync`/`spawnSync` with argument arrays throughout.
- **Secret handling.** `lib/secrets.ts` opens the store with `O_NOFOLLOW`, refuses to read it when group/other permission bits are set, validates names against `^[A-Z][A-Z0-9_]*$` and values against NUL/newline/16 KiB, and never returns a secret value in metadata. The tailscale registry is written with mode `0o600`.
- **Prompt/response hygiene in traces.** `server/tool-arguments.ts:124-181` stores a **fixed allowlist** of provider error codes in the trace rather than the provider's message, which could echo the request — an explicit, well-designed defence against credential leakage into logs.
- **Terminal escape injection.** `bin/dashboard.ts:6-10` strips VT control characters from child output before it reaches the terminal or the log.
- **ANSI sanitisation.** Control sequences are consumed whole (CSI/OSC/DCS) before individual controls are stripped, in both the app (`web/src/components/ai/ansi-output.tsx:4-12`) and the patched dependency (`patches/@earendil-works__chord@1.4.0.patch`) — so an OSC payload cannot leak into visible text.
- **Project-extension trust boundary.** Project extensions load only when `useProjectSetup()` is true (`server/discovery.ts:43`); the decision is written server-side into `~/.ultimate/trust.json` through Pi's `ProjectTrustStore` (`server/extensions.ts:397-403`), keyed by the project's decision root so a git worktree inherits its main checkout's decision (`server/project-setup.ts:36-51`). The user is asked explicitly through the onboarding card (`extensions/onboarding/server.ts:419-425`), and the agent cannot grant itself trust — `setExtension` refuses to act on project scope unless the decision is already `true` (`extensions/onboarding/server.ts:435-437`).
- **Locking.** `server/lock.ts` uses SQLite `BEGIN EXCLUSIVE` with an owner sidecar and a liveness check; `retireStorageOwner` refuses to signal a pid whose command line is not `server/main.ts` (`server/lock.ts:33-34`) — a nice guard against PID reuse.
- **Atomic state writes.** `lib/json-file.ts:41-61` writes via temp file + `fsync` + `rename`, following symlinks deliberately (`writeTarget`) so a dotfiles-repository symlink stays linked, with a per-path serialisation map so read-modify-write is serialised in-process.
- **Dependency-level supply-chain defence is strong.** `packageManager` pins pnpm 11, whose defaults refuse to resolve a package version published less than 24 hours ago, block non-registry transitive dependencies, block dependency build scripts outside an explicit allowlist, and fail the install loudly rather than silently skipping one. The project's `allowBuilds` and `minimumReleaseAgeExclude` lists are both minimal and deliberate, and the `overrides` entry documents the advisory it answers. The one defect is a stale placeholder (SC3).
- **Browser isolation.** `extensions/browser/server.ts` launches Playwright's own Chromium with a fresh profile — it never attaches to the operator's real browser profile, so it cannot read their cookies, saved passwords, or history.
- **Cross-origin file reads.** Vite's dev server keeps its default CORS policy (localhost origins only) and `server.fs.allow` is restricted to the clone, the project, and `~/.ultimate` (`server/main.ts:121-123`).
- **Empty catches.** All 57 empty `catch {}` blocks in shipped code carry an explanatory comment, enforced by the `ultimate/no-silent-catch` lint rule.
- **Effect cleanup.** Every `useEffect` that starts a timer, an interval or a subscription in `web/src/` returns a matching cleanup (`web/src/sdk/hooks.ts:535,548-554`; `web/src/sdk/store.ts:299-300,389,446,454`).
- **Reduced motion.** `prefers-reduced-motion: reduce` disables every animation and transition globally (`web/src/index.css:223-230`).
- **Token discipline.** Only three hard-coded hex colours exist in the whole UI; everything else is a token. Radii, spacing and shadows come from one scale.

---

## Prioritised remediation plan

| # | Action | Effort | Risk if fixed | Addresses |
|---|---|---|---|---|
| 1 | Add a CSP with `frame-ancestors 'none'` + `X-Frame-Options: DENY` on every response | 1 h | Low | S1, S2 |
| 2 | Add `Cache-Control: no-store`, `nosniff`, `Referrer-Policy: no-referrer` to `/api/*` and the HTML | 30 min | Low | S2 |
| 3 | Add `.github/workflows/ci.yml` (install → `pnpm check` → `pnpm test` → `pnpm test:e2e`) and make it a required check | 2 h | Low | R1 |
| 4 | Recompute and fix the light-theme `--success` / `--warning` / `--note` tokens to clear 4.5:1 on both `--background` and `--card` | 1 h | Low (visual) | A3 |
| 5 | Make `--ring` opaque and drop the `/50` modifier on focus rings; add a contrast assertion to the token file | 1 h | Low (visual) | A1 |
| 6 | Darken `--input` to ≥3:1 against `--background` and `--card` | 1 h | Low (visual) | A4 |
| 7 | Introduce named dimmed-text tokens that are contrast-safe and migrate the `/70`, `/60`, `/50` usages in batches | 1–2 days | Medium (visual churn) | A2 |
| 8 | Add a client `requestId` to submissions and make the server treat a repeat as the same submission | 0.5 day | Medium (touches the submit path) | R3 |
| 9 | Merge rather than replace in `refreshConversations`; recompute `busy` for every summary | 30 min | Low | R2 |
| 10 | Add `SECURITY.md` with a private address; enable GitHub private vulnerability reporting | 30 min | None | SC4 |
| 11 | Invert the action CSRF guard to a positive same-origin check | 30 min | Low | S3 |
| 12 | Migrate the px type scale to `rem` in batches, starting with the 8.5/9.5/10/10.5 px sizes | 2–3 days | Medium (layout churn) | A5, V2 |
| 13 | Rotate `supervisor.log` at a size threshold | 30 min | Low | R5 |
| 14 | Verify upstream commits before fast-forwarding, or pin updates to reviewed tags | 1 day | Medium | SC2 |
| 15 | Delete the stale `workerd` placeholder from `allowBuilds`; add a CI check that every `allowBuilds` value is a boolean and names a package in the lockfile | 30 min | None | SC3 |
| 16 | (Optional) Gate the automatic `pnpm install` behind the existing restart prompt | 1 h | Low | R4 |
| 17 | Add `aria-hidden` to decorative SVGs | 30 min | Low | A6 |
| 18 | Derive `--error` from `--destructive` | 15 min | Low | V1 |

---

## Quick wins (low regression risk, safe to land first)

1. **Security headers on every response** (S1, S2) — one `writeHead` change in `server/main.ts` plus `reply()` in `server/api.ts`. Highest value per line in this report.
2. **CI workflow** (R1) — pure addition, no product risk, and it protects every future change.
3. **`SECURITY.md` + private vulnerability reporting** (SC4) — a file and a repo setting.
4. **Light-theme token contrast fixes** (A3, A4, A1) — three token values plus one modifier. Verify visually; no structural change.
5. **Merge instead of replace in `refreshConversations`** (R2) — a few lines in one function, and the subscriber's own pattern is the reference implementation.
6. **`supervisor.log` rotation** (R5) — a size check before `appendFileSync`.
7. **Invert the action CSRF guard** (S3) — one condition.
8. **Return `409` on a duplicate subscription id** (R6) — one line.
9. **`aria-hidden` on decorative icons** (A6) — one wrapper.
10. **Derive `--error` from `--destructive`** (V1) — one token.
11. **Delete the stale `workerd` placeholder** from `allowBuilds` (SC3) — one line; nothing in the tree depends on it.

---

## Issues needing architectural change or deeper investigation

1. **The type scale (A5, V2)** — 948 fixed-px font sizes across 119 files cannot be fixed by lint; it needs a token migration and a layout pass. It should be paired with a decision about whether the dense chrome is worth the accessibility cost, and with a text-spacing (WCAG 1.4.12) test.
2. **Dimmed-text semantics (A2)** — 284 opacity-modified text usages encode a visual hierarchy the token set does not express. The fix is a semantic token layer (`--text-muted`, `--text-subtle`, `--text-disabled`) with guaranteed contrast, plus a migration that forces every call site to choose one deliberately.
3. **Submission idempotency (R3)** — needs a `requestId` plumbed through the client, the API and the durable layer, plus server-side dedupe semantics for the "queued" path (a steer that merges with a queued follow-up). Pi Durable's `submit` already accepts a `requestId`, so the primitive exists, but the dedupe window and the interaction with `whenBusy` need designing.
4. **The `busy`/summary state model (R2)** — two writers mutate one array. The durable fix is a single serialised updater (or making the graph the single source of truth for `busy` and deriving the list from it), not another merge patch.
5. **Release signing and provenance (SC1)** — needs a release pipeline, a signing key custody decision, and a policy for what the signed artifact covers. Nothing exists today.
6. **Upstream trust (SC2)** — requiring signed commits on `main` changes the maintainer's workflow and needs a decision about enforcement (server-side hook vs. client-side verify) and a key distribution story.
7. **Tailscale identity (S4)** — the trust placed in Serve's header semantics should be confirmed against current Tailscale behaviour, and the code made to fail closed under an unexpected proxy topology.
8. **CI scope (R1)** — with 214 test files and a custom lint plugin, deciding what runs on a PR (fast suite) versus on `main` (full suite + e2e) is a policy call, not just a YAML file.

---

## Release recommendation

**Ship with known risks.**

Justification:

- **Nothing found is remotely exploitable.** The server binds loopback only; the origin/identity gate is sound; cross-site state-changing requests are rejected; the project-extension trust boundary is real and user-mediated; there is no obfuscation, no telemetry, no unexplained egress, and no credential access outside the tool's own configuration.
- **The material risks are conditional on the user being at the machine** — clickjacking (S1) needs the user to load a hostile page and interact with the overlay; the supply-chain findings (SC1, SC2) need a compromised `origin`; the disclosure gap (SC4) is a governance risk rather than a vulnerability.
- **The confirmed accessibility defects are real and user-facing** (A1–A5) and affect every user of the light theme and every user who raises their font size. For a product whose pitch is a long-lived daily work surface, that is the most consequential group of findings, and it is worth fixing before the light theme is promoted.
- **The absence of CI (R1)** is the finding most likely to cause the next incident: nothing verifies a change before it lands, and the project authorises direct pushes. Land CI first.
- **If this were shipping to users rather than to its author** — a hosted multi-tenant deployment, or a distribution where the operator is not the developer — the recommendation would change to **do not ship** until S1, S2, SC1, SC2 and SC4 are closed, because the loopback assumption, the single-maintainer trust model and the unsigned update path all become liabilities at that point.

---

## Trust-model statement

**Is it safe to install and run on a primary machine?** Yes, with the caveat that this is a local-first developer tool whose whole purpose is to execute model-authored code — including `bash` — inside your project directory, with no per-command approval. That is the product, not a defect. On top of that baseline, the audit found **no hidden behaviour**: nothing phones home, nothing collects telemetry, nothing reads your SSH keys, browser profile, keychain or cloud CLI configuration, nothing persists beyond one opt-in service unit and one opt-in Tailscale mapping, and nothing is obfuscated. Every network destination the shipped code contacts is listed above and explained. I found no malicious code.

**What could an attacker do to the operator, if the findings were exploited?**

- **Via clickjacking (S1):** an attacker-controlled page frames the Ultimate UI and overlays it. The user, believing they are clicking something else, can be induced to submit an attacker-written prompt into their own agent. Because the agent has unrestricted `bash` access to the project directory, that becomes arbitrary code execution in the user's project — under the user's own account, with the user's credentials in the environment, in a directory the user trusts. The attacker does not get the conversation contents (the frame stays cross-origin), but they get to choose what the agent does.
- **Via the update path (SC2) plus the unattended install (R4, SC3):** anyone who can push to `origin` gets code execution on every operator's machine at the next hourly fetch — no signature to forge, no checksum to compare against, no release artifact to verify (SC1). This is the classic "trusted dependency" compromise, and the project has no second factor.
- **Via a project you check out (by design, but worth stating):** if you trust a project's `.ultimate/` setup, its extensions run as server-side code with full Node privileges. A malicious repository you open once, and whose setup card you accept, is arbitrary code execution. The consent is explicit and one-time — but it is one-time, and the decision is remembered per git checkout.
- **Via the browser tool (S6):** a prompt-injected agent can browse to your local API. The data it reaches is already reachable through `bash`, so this is not an escalation — but it means "the browser is sandboxed" is not true.

**Concrete mitigation guidance:**

- **Pin your checkout.** `git clone` then `git rev-parse HEAD` and record it. Re-verify on every `Ultimate: Update now`. Do not let `origin/main` be your only trust anchor.
- **Treat `origin` as a production credential.** Protect it with branch protection, require signed commits, and enable 2FA. Nothing in the project enforces this for you.
- **Read the trust card before accepting it.** The trust decision is one-time and per checkout; when a repository asks, look at `.ultimate/extensions/` first, as you would any `Makefile` you are about to run.
- **Keep the machine out of scope.** Run Ultimate in a container, a VM, or a disposable worktree when the project is untrusted or the work is sensitive. The `bash` tool has the full privileges of the user who started it.
- **Do not expose the instance beyond the tailnet.** If you enable the Tailscale extension, keep `tailscale.allow` to the smallest set that works — the instance is a full agent with filesystem access, and the identity check is a header.
- **Build from source and keep the dependency layer pinned.** `pnpm install --frozen-lockfile` verifies every package against the lockfile's integrity hash, pnpm 11 refuses to resolve any package published in the last 24 hours, and dependency build scripts run only for `esbuild`. Keep it that way: do not relax `--frozen-lockfile`, do not set `minimumReleaseAge: 0`, and do not add entries to `allowBuilds` without reading the package's install script first.
- **Prefer the loopback path.** Do not port-forward or reverse-proxy the instance to a public interface. The admission logic assumes one hop in front of it and a loopback Host.
- **Do not rely on a browser's private window for isolation.** The loopback admission path deliberately admits cross-site navigations, so a hostile page can frame the UI.

---

### Artifacts

- `contrast.py` (alongside this report) — the WCAG contrast computation used for A1–A4, derived from the tokens in `web/src/index.css`. Re-runnable against any token change:
  ```bash
  python3 contrast.py
  ```
