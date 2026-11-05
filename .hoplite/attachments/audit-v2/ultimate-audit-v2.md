# Ultimate — Corrected Audit and Remediation Plan

**Target:** `pt-act/ultimate` at `c00bea3` (2026-10-31), verified against `87f9a6e` (2026-11-01, +47 commits).
**Supersedes:** `ultimate-audit-report.md` (v1) for the findings listed under "Corrections".
**Method:** every claim below was re-derived at `c00bea3` in a detached worktree. Executable claims were
reproduced (admission probes, WCAG math, pnpm installs, rendered icons), not re-read from v1.

**Status (2026-11-01): phases 1, 2, 3.1 and 3.2 are implemented.** See "Remediation status" at the end for what
landed, what was verified, and the two places this plan changed while doing it.

## Verdict

**Ship with known risks — unchanged.** No Critical or High finding survives scrutiny. One finding (S1,
clickjacking) is confirmed by execution and is the only remotely reachable issue; it requires the victim to visit a
hostile page while the instance runs. The most valuable remediation is still CI, and it is cheap.

The v1 report reached the right verdict but is not safe to work from as written: three findings are false
positives, two carry unverifiable numbers, and two fix recommendations do not achieve their stated targets.

---

## Corrections to v1

### Withdrawn — not defects

**R2 (stale `busy` flags) — false positive.** v1 claims a race between `refreshConversations` (`server/api.ts:222`)
and the graph subscriber (`:243-262`). The snapshot at `:223` and the write at `:236` are separated by **zero
`await`s**, so no interleaving is possible; the graph writer is synchronous too. The comment at `:222` documents
the concern as already handled, and `test/conversations-summary.test.ts` covers it — I ran it, 2/2 pass.

**A6 (icons announced by screen readers) — false positive.** `lucide-react` 1.49.0 emits `aria-hidden="true"`
by default when no a11y prop is present (`buildLucideIconNode.mjs:47-49`). Rendering `<Check/>` produces
`<svg … aria-hidden="true">`. The five raw `<svg>` elements already carry `aria-hidden` or `role="img"` +
`aria-label`. No change needed.

**Duplicate subscription direction — inverted.** A duplicate `sub` makes the **new** subscription back out
(`server/api.ts:368-371`, `await stop()` on its own local closure) and return `{ok:true}`; the existing one keeps
running. v1 states the reverse. Behavior is acceptable — the shipped client never reuses ids — but the recommended
`409` is optional polish, not a correctness fix.

### Corrected numbers

**A1 (focus ring).** v1 reports 2.71:1 dark / 1.28:1 light. Those match neither the rendered result nor its own
`contrast.py` (4.42 / 1.79). The script composites in linear space and applies the token alpha **once**; the
browser composites in gamma space and applies it **twice** (token `0.5` × utility `/50`). Browser-accurate:

| Theme | `--ring` alpha only | as rendered (`/50` on top) |
|---|---|---|
| Dark | 2.81:1 | **1.57:1** |
| Light | 2.23:1 | **1.46:1** |

The finding stands and is worse than reported; the quoted figures are wrong. Drop the alpha entirely rather than
tuning it — an opaque ring passes comfortably in both themes (7.84/7.52 dark, 5.02/4.80 light).

**A4 (input borders) — recommended values miss the target.** v1 suggests `oklch(0.72 0.01 270)` light and
`oklch(0.42 0.008 270)` dark. Those measure **2.38:1** and **2.23:1** — still short of 3:1. Verified instead:
light needs `L ≤ 0.64` (3.22/3.09), dark needs `L ≥ 0.50` (3.14/3.02).

**A2 (opacity text) — scope overstated.** v1 says opacity-modified text fails "hundreds of times". Measured:
`text-foreground/{70,75,80,85,90}` **all pass** (6.13–12.49:1 both themes). Only `text-muted-foreground/*` fails,
and only at `/80` or below, in both themes. The real defect is narrower and more tractable than described:

| Step | Light | Dark | Verdict |
|---|---|---|---|
| `/80` | 3.72 | 4.00 | FAIL |
| `/75` | 3.36 | 3.66 | FAIL |
| `/70` | 3.05 | 3.34 | FAIL |
| `/60` | 2.52 | 2.77 | FAIL |
| `/50` | 2.11 | 2.29 | FAIL |
| `/40` | 1.79 | 1.88 | FAIL |

318 occurrences across 88 files. Note `/70` alone is 161 of them.

**SC3 (`workerd` placeholder) — understated in v1's summary, correctly rated Low.** The v1 summary calls it a
supply-chain gap while its own detail section calls it inert. I tested pnpm 11.8.0: a non-boolean value is
silently treated as absent, the named package gets no build script, and install otherwise succeeds. `workerd`
appears nowhere in `pnpm-lock.yaml`. Cosmetic, but worth deleting.

### Reframed

**R1 (no CI) — real, but the impact text overreaches.** v1 says "nothing runs `pnpm check` or `pnpm test` before a
change lands." The lander does run configured checks before pushing (`extensions/workspaces/lander.ts:620-660`,
configured at `.ultimate/settings.json` as `pnpm check`, `pnpm test`, and `pnpm test:e2e`). What is genuinely
missing is an **external** gate for contributions that bypass the lander — direct pushes and outside pull requests.
That is still worth fixing, and the framing matters because a reader who checks the claim will find it false.

**A3 (status colors) — real in light mode; note the icon split.** Light-theme `success` 4.33:1, `warning` 3.89:1,
`note` 2.21:1 all fail the 4.5:1 text threshold. `note` has exactly **one** usage and it is an icon, so it is not
a text-contrast defect at all. Of 55 `text-success` and 107 `text-warning` usages, 19 and 12 are icons
(3:1 threshold, all pass); the remaining 36 and 95 are real text and need the color change.

### Confirmed as written

Volume metrics all reproduce exactly at `c00bea3`: 824 files, 139,511 TS/TSX lines, 214 test files, 948
`text-[…px]` across 119 files, the 16-step size histogram, `head` font-size 14px at `index.css:209`, 4 hex
colors, zero `0.0.0.0`, zero `eval`/`new Function`, zero empty catch bodies (41 carry leading comments).
`no CI`, `no SECURITY.md`, missing response headers, the inverted extension-action guard, and Tailscale's
header-derived identity all confirmed. `pi-durable` **does** support `requestId` deduplication
(`types.d.ts:437`, `submissionByRequest`, `:849`), so R3's fix is smaller than v1 implies.

---

## Confirmed findings, by remediation phase

### Phase 1 — Land in one sitting (low risk, high value)

**1.1 CI workflow.** `.github/workflows/ci.yml`: pnpm 11.8.0 via `corepack`, Node 26, `pnpm install
--frozen-lockfile`, then `pnpm check`, `pnpm test`, `pnpm test:e2e` on `pull_request` and `push` to `main`.
`pnpm test:e2e` needs `playwright-core` browsers — add `pnpm exec playwright install --with-deps chromium` or
split e2e into a separate job gated on it. Make the aggregate required on `main`.

**1.2 Security headers.** Add to `server/main.ts` before both the API and Vite paths (`:78-88`):
`Content-Security-Policy: frame-ancestors 'none'; object-src 'none'; base-uri 'none'`,
`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. Add
`Cache-Control: no-store` for `/api/*` and HTML. Keep the CSP minimal — `web/index.html` has two inline
`<script>` blocks (`:28`, `:37`) that theme-resume boot depends on, so a nonce-based `script-src` is a separate
piece of work; `frame-ancestors` needs neither and closes the clickjacking hole immediately.

**1.3 Fix the admission bypass.** S1's root cause is ordering in `server/request-security.ts:39-45`: the
loopback branch returns `true` before `Sec-Fetch-*` is consulted. Require `sec-fetch-site` ∈
`{same-origin, none}` (or absent) on the loopback branch, and reject `sec-fetch-dest: iframe` outright. Headers
in 1.2 are the defense an older browser sees; this closes the hole in the code. Add a test asserting a
`cross-site`/`iframe` GET of `/` is rejected — I verified it is currently **admitted**.

**1.4 Invert the extension-action guard** (`server/api.ts:127-128`) to a positive same-origin check:
`sec-fetch-site === 'same-origin'` or `Origin === request origin`. Currently a cross-site request carrying an
`Origin` header passes this check; only `admit()` stops it.

**1.5 Delete the `workerd` line** from `pnpm-workspace.yaml:5`.

**1.6 `SECURITY.md`** with a private reporting channel; enable GitHub private vulnerability reporting.

### Phase 2 — Contrast (one coordinated token pass)

Do these together: each changes a token another depends on.

- **`--ring`**: make opaque in both themes. Dark `oklch(0.74 0.13 300)` → 7.84:1; light
  `oklch(0.55 0.17 300)` → 5.02:1. Twelve sites dilute it further — `ring-ring/50` ×4, `/40` ×7, `/30` ×1,
  eleven of them under `extensions/`. Drop the opacity modifiers so every focus ring uses the token at full
  strength; `web/src/components/ui/button.tsx:7` is the `/50` behind the worst measured ring.
- **`--input`**: light `L 0.86 → 0.64` (3.22:1); dark `L 0.30 → 0.50` (3.14:1). 10 `border-input` sites.
- **`--muted-foreground`**: light `L 0.50 → 0.42`; dark `L 0.64 → 0.72`. This makes `/80` pass in both themes
  (4.78/4.64 light, 5.25/5.10 dark). The single `/75` still misses at `L 0.42` (4.22 light); it needs
  `L ≤ 0.389`, or just retarget that one site.
- **Opacity utilities**: after the token change, `/70` (161 sites) still fails. Either raise those to `/80`, or
  add a `--muted-faint` token computed to pass at `/70` (light `L ≤ 0.34`, dark `L ≥ 0.74`) and swap the
  utility. Prefer the named token — it stops the next `/60` from being invented.
- **`/60`, `/50`, `/40`** (122 sites): these cannot reach AA at any token lightness on the current background.
  Light-theme `/50` tops out at 3.91:1 even for pure black text, so no token change can save it. Audit each:
  separators, `$` prompts, and gutter glyphs are decorative and may legitimately sit at the 3:1 non-text
  threshold or be exempt; anything that is real prose must move to a passing step.
- **Light `--success`** → `L 0.55 → 0.52` (4.87/4.66); **`--warning`** → `L 0.60 → 0.55` (4.77/4.57).
  Leave `--note` alone — its only use is an icon.

### Phase 3 — Structural

- **3.1 Submission idempotency.** `pi-durable` already accepts `requestId` on submissions and exposes
  `submissionByRequest`. Thread a client-generated id through `api.submit`, dedupe in `server/api.ts:581`, and
  return the existing `submissionId` on replay. Smaller than v1 described.
- **3.2 `supervisor.log` rotation.** Cap at a size threshold in `bin/dashboard.ts:44-50`, rename to `.1` on
  rollover, and truncate on successful start. Update the README sentence at `README.md:117`.
- **3.3 Type scale.** 948 fixed-px sizes across 119 files, smallest `text-[8.5px]`. Migrate to `rem` in passes
  by size, smallest first, with a visual check after each pass. This is the largest and least urgent item; it
  does not block anything else.
- **3.4 Optional polish.** Return `409` on duplicate subscription ids; derive `--error` from `--destructive`;
  verify the Tailscale Serve header contract and document the assumption.

### Not planned

Commit-signature verification on the updater (v1's SC2): the updater fast-forwards a branch the operator already
trusts and already records object hashes. Signature verification adds key-custody work for a threat the loopback
trust model does not otherwise defend against. Revisit only if distribution to third-party operators happens.

---

## Verification per phase

| Phase | Proof |
|---|---|
| 1.1 | Workflow run green on a scratch PR; deliberately break a type and confirm red |
| 1.2 | `curl -sD- http://127.0.0.1:4747/` shows all four headers; app boots and theme-resume still works |
| 1.3 | New test: cross-site `iframe` GET → 403. Existing admission tests unchanged and green |
| 1.4 | Probe the guard truth table; cross-site + `Origin` now throws |
| 1.5 | `CI=true pnpm install --frozen-lockfile` succeeds; `allowBuilds` has three entries |
| 2 | Re-run `contrast.py` extended to composite in gamma space at the rendered alpha; every text pair ≥ 4.5, every control ≥ 3. Screenshot both themes |
| 3.1 | Submit twice with one id; one durable message. Test at the API layer |
| 3.2 | Write past the cap, confirm `.1` appears and the live file is bounded |
| 3.3 | Set browser font size to 24px, confirm the UI scales |

## Sequencing note

Phase 1 is independent and should land first — 1.1 in particular turns every later phase into a checked change.
Phase 2 is one coordinated pass; splitting it leaves the palette in a state where a fix for one pair breaks
another. Phase 3 items are independent of each other and of Phase 2.

---

## Remediation status

Implemented in this branch. Each row states what changed and how it was verified.

| Item | Change | Verified by |
|---|---|---|
| 1.1 CI | `.github/workflows/ci.yml`: `check` job (install, `pnpm check`, `pnpm test --maxWorkers=2`) and a separate `e2e` job that installs Chromium and sets a Git identity | Green on `7143b2c`: check 5m20s, e2e 3m59s |
| 1.2 headers | `securityHeaders` in `server/main.ts`, set on every response before either handler | `curl -sD-` on `/` and `/api/*` shows CSP, `X-Frame-Options`, `nosniff`, `no-referrer`, `no-store` |
| 1.3 framing | `admit()` refuses a `cross-site` iframe; same-site frames and cross-site root navigations still pass | 12-case truth table + `test/request-security.test.ts` |
| 1.4 CSRF guard | `runAction` uses a positive same-origin check instead of the inverted one | Guard truth table; existing extension-action tests green |
| 1.5 `workerd` | Line removed from `pnpm-workspace.yaml` | `CI=true pnpm install --frozen-lockfile` |
| 1.6 disclosure | `SECURITY.md` with private reporting and scope | — |
| 2 contrast | Tokens retuned; all 12 `ring-ring/*` call sites made opaque; `--error` derived from `--destructive` | `test/theme-contrast.test.ts` (7 checks), computed styles read from the running app in both themes |
| 3.1 idempotency | `requestId` on `SubmitRequest`, threaded through `conversation.submit`, held across a composer retry | Live: two POSTs with one key → one `submissionId`, one `pi.user` entry; `test/server.test.ts` |
| 3.2 log rotation | 8 MiB cap in `bin/dashboard.ts`, renamed to `supervisor.log.1`; README updated | `test/dashboard.test.ts` |

### Where this plan was wrong, and what changed

**`frame-ancestors 'none'` would have broken the instance preview.** `extensions/instance/web.tsx` frames another
running Ultimate on its own port — a same-site load whose origin differs. The header now names loopback and tailnet
hosts as allowed ancestors, and `admit()` refuses only `cross-site` frames. Both behaviors have tests.

**The status colors needed a wider fix than background/card.** `--success` and `--warning` are also drawn on
`--muted` and `--accent` chips, where the light values had to go darker again (0.499 and 0.525) to clear 4.5:1.
`--error` is now `var(--destructive)`, which also resolves the V1 token divergence.

**Dimmed text needed one more step than /80.** `text-muted-foreground/70` is 161 sites of real prose, so the tokens
were darkened until `/70` clears AA on the darkest surface (`--accent`): light `L 0.317`, dark `L 0.78`.

### A defect this plan introduced, and fixed

The first cut of `frame-ancestors` listed `http://[::1]:*`, which is not a valid source expression — a host source
may not carry a port range with an IPv6 literal. A browser drops the **whole** directive when any expression fails
to parse, so the header was present but refused nothing: a cross-site iframe rendered the entire transcript. Caught
in a real Chromium check during the merge-readiness pass, not by review. Verified fixed: the cross-site frame is
refused, the same-site preview frame across ports still renders, and `test/security-headers.test.ts` fails if an
unparseable expression returns.

### Still open

- **Phase 3.3, the type scale.** 948 fixed-px sizes remain; it is the largest item and blocks nothing else.
- **The 122 sites at `/60`, `/50`, `/40`.** These cannot reach AA at any token lightness. Each needs a judgement:
  decorative separators and glyphs may sit at the 3:1 non-text threshold, real prose must move up a step.
- **CI runs green** on `7143b2c` (both jobs pass). The browser e2e case `questions-keyboard` timed out once on a 2-core runner and passed on rerun; it sits close to its 60 s limit.
- **Commit-signature verification** remains deliberately out of scope, as argued above.
