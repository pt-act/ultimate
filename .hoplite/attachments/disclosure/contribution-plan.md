# Getting the remediation upstream

**State:** `pt-act/ultimate` `main` is at `4f380f54`, CI green, merged from PR #1. `HazAT/ultimate` is at `e2b9fa6`
and **still has every finding** in `upstream-disclosure.md`.

## What we cannot do, and why

The workspace credential is a GitHub App installation token scoped to `pt-act/ultimate`. It cannot create a pull
request on `HazAT/ultimate` — attempting it returns `Resource not accessible by integration (createPullRequest)`. So
the push upstream is yours to make.

This is not a token we should widen: the alternative (a personal access token, or a broader installation) is a
standing grant for a one-off action. Use the GitHub web UI instead.

## The maintainer's stated position

`CONTRIBUTING.md` matters more than usual here, because it asks for less than a reviewer normally would:

- **"Pull requests are welcome as shared ideas. Most stay open, unmerged, as references anyone's Ultimate can adopt."**
- **"Merging is the exception, for clear-cut fixes or improvements to the core."**
- **Issues are not reviewed**, and there is no `SECURITY.md` and no private reporting.

So expect a reference, not a merge. That is the normal outcome and not a judgement of the work.

## Recommended sequence

### 1. Tell the maintainer privately first (a day or two before any public PR)

There is no private channel in the repository, so use whatever contact is on the maintainer's GitHub profile. Attach
`upstream-disclosure.md` and keep the ask narrow:

- The clickjacking finding, with the two-step reproduction.
- An offer of the self-contained fix, or to let them write it their way.
- No request for credit, no deadline, no public disclosure threat.

The reason to go private first is not secrecy for its own sake — the finding is not remotely exploitable without a
user visiting a hostile page — but because a public report of a clickjacking hole in a tool whose agent runs `bash` is
an invitation for someone to try it before a fix exists.

If they enable private vulnerability reporting at this point, use it, and keep it there.

### 2. Offer the smallest PR first

If they are receptive, the anti-framing fix alone is the one to send: `server/main.ts` headers plus the `admit()` check
and its tests. It is small, self-contained, closes the only finding that needs no unusual conditions, and does not
carry the 182-file type-scale diff.

Send it as a fresh branch off `origin/main` of the fork, containing only that change — not the whole PR #1 branch. A
reviewer facing 182 files for a security fix will defer it.

### 3. Then the rest, separately, if wanted

One idea per pull request, per `CONTRIBUTING.md`. The natural split:

| PR | Contents | Size |
|---|---|---|
| Security headers + framing | `server/main.ts`, `server/request-security.ts`, tests | small |
| Guard + cache + idempotency | `server/api.ts`, `shared/protocol.ts`, composer, tests | small |
| Contrast | `web/src/index.css`, ring/opacity call sites, `test/theme-contrast.test.ts` | medium |
| Type scale | 121 files to `rem`, `test/type-scale.test.ts` | large, mechanical |

The type scale is the one to file last, or as a reference only, because it collides with every concurrent UI change.

## Mechanics, when you have the credentials

**The minimal branch already exists and is pushed:** `upstream/anti-framing`, commit `751b5e44`, four files and 165
lines on top of upstream `e2b9fa61`. It passes `pnpm check` and its 20 tests. It is on the fork, so the pull request
is one page away:

https://github.com/HazAT/ultimate/compare/main...pt-act:upstream/anti-framing?expand=1

The branch is built on upstream's `main`, not the fork's, so the diff contains only the framing fix — no audit
remediation, no type scale. If it needs rebuilding: `git checkout -b upstream/anti-framing e2b9fa61`, take
`server/main.ts`, `server/request-security.ts` and the two tests from `4f380f54`, and drop the `Cache-Control` block
from `main.ts`.

## What not to do

- **Do not open a public issue with the reproduction** — `CONTRIBUTING.md` says issues are not reviewed, so it would
  be a public write-up with no reader.
- **Do not post the audit report as a comment on an unrelated PR.** There are 73 forks and a dozen open feature PRs;
  that is noise, not disclosure.
- **Do not claim the repository is insecure in the PR title.** Describe the change, state the effect, show the
  before/after in the body.
- **Do not send the branch from before the upstream merge.** It would conflict on the `mcp`/`sounds` files where
  upstream added `px` sizes and we converted them; branch off current `main` instead.

## Ready-to-use title and body

**Title:** `Close clickjacking: refuse cross-site frames and send anti-framing headers`

**Body** (trim to taste; the disclosure document has the detail):

> `admit()` returns `true` for a loopback `Host` with no `Origin`, and browsers send no `Origin` for a framed load, so
> any page can frame the UI at `127.0.0.1:4747`. No anti-framing header is sent either:
>
> ```
> curl -sD- -o /dev/null http://127.0.0.1:4747/ | grep -iE 'frame|content-security'   # nothing
> ```
>
> Since the agent runs `bash` with the operator's privileges, an overlay on the composer is a way to have the user's
> own click submit a command.
>
> This refuses a `cross-site` frame in `admit()` and adds `frame-ancestors`, `X-Frame-Options`, `nosniff` and
> `no-referrer` to every response. `frame-ancestors 'none'` is deliberately not used: `extensions/instance/web.tsx`
> frames another instance on its own port, so the header names loopback instead, and same-site frames and cross-site
> root navigations stay admitted.
>
> One trap, because it cost us a false pass: `http://[::1]:*` is not a valid source expression, and a browser drops
> the **whole** directive when one expression fails to parse — the header was present and refused nothing. The test
> asserts the effect in a browser, not the header's presence.

## Outcome (2026-11-04)

Upstream merged PR #74 with a follow-up (`eee453d9`, "Framing: allow *.localhost parents and drop the admit()
rewrite"). Their testing caught a real defect in ours: the supervisor opens the app at `http://ultimate.localhost:<port>`,
and a preview framed from that window to another loopback port is *cross-site* (`sec-fetch-site` compares hostnames,
not ports), so the `admit()` rewrite answered 403 there — and the CSP, which listed only `127.0.0.1`/`localhost`,
blocked it too. Verified against the fork: `curl --resolve ultimate.localhost:4747:127.0.0.1` with iframe metadata →
403, and the served CSP has no `*.localhost`.

They took the headers as the single layer, added `http://*.localhost:*`, and restored `admit()`. The lesson for the
fork's next sync: adopt their resolution wholesale — our diverging `admit()` layer is the defective variant, and
keeping it would preserve a preview breakage upstream does not have. Private vulnerability reporting upstream is still
off, and there is still no `SECURITY.md`, so the other two asks remain open.

## Fork sync with the framing resolution (2026-11-04, later)

PR #3 (pt-act/ultimate) merged upstream main (eb19f7b8, 45 commits) and adopted
their framing resolution wholesale: their main.ts (frame-ancestors now includes
http://*.localhost:*), their restored admit(), their tests. Our diverging
admit() variant is gone; the preview breakage upstream does not have is gone
here too. Nine other conflicts kept upstream's code with our hardening
(useAgentTitle rename, data-ui attributes, requestId retry key); upstream's new
components reintroduced 12 px text sizes, which the guards caught, re-hardened.
pnpm check passed (863 files); 69 tests passed.

CI taught one more lesson: upstream's follow-up enabled Chromium's sandbox by
default in the browser extension (Playwright's default had it off). The CI
runner cannot start the sandbox, so both launching browser tests died with
"Running as root without --no-sandbox". The documented knob
(ULTIMATE_CHROMIUM_SANDBOX=0) cannot be delivered via CI env: test/helpers.ts
strips every ULTIMATE_* variable from worker env. Fix: stub it in the two
launching tests (0225c08c); be9fe829 dropped a useless job-level env override.
Upstream's CI does not run e2e, so the gap is invisible to them - worth telling
them (helpers.ts strips the knob their README documents for exactly this case).

Final fork state: main f6e92b45, upstream eb19f7b8 an ancestor, 0 behind.
Still open upstream: private vulnerability reporting off, no SECURITY.md.

## Upstream e2e sandbox PR (2026-11-05)

Branch pt-act/ultimate:e2e-chromium-sandbox-knob (1d653112, on upstream tip
eb19f7b8): stubs ULTIMATE_CHROMIUM_SANDBOX=0 inside the two browser-launching
tests of test/e2e/browser.test.ts, since test/helpers.ts strips ULTIMATE_* from
worker env and CI env cannot deliver the knob. Verified on the upstream tree:
baseline 2/3 fail as root, with stubs 3/3 pass; pnpm check green. PR creation on
HazAT/ultimate is outside the workspace credential scope ("Resource not
accessible by integration"), so the user opens it via the compare URL with the
approved title and body.

## PR 4 conflict resolution and CI (2026-11-05)

Merged origin/main into e2e-chromium-sandbox-knob (b012a976): the only conflict
was the two wordings of the stub comment (main had the same stub from the sync's
0225c08c); took the branch wording, warmups merged cleanly. Merged file: 3/3
tests pass, pnpm check green. Pushed with plain refspec (merge keeps history).
PR 4 now MERGEABLE and CI ran for the first time on it: run 42045091226, both
jobs green including End to end on the fork runner - CI evidence for the warmup
fix. Fork main still red (old head, needs the PR 4 merge). PR 85 now carries
b012a976 automatically.

## PR 4 merged (2026-11-05)

Fork main 977180ed has b012a976 (stubs + warmup) merged; CI run 42046529993
green, both jobs, so fork main is green again. PR 85 open at b012a976; the user
amended its description (confirmed live 2026-11-05 14:35, covers both commits
and the CI evidence). No maintainer reply yet. Remaining audit asks: private
reporting, SECURITY.md.

## SECURITY.md contribution (2026-11-05)

Branch pt-act/ultimate:security-policy (c21f2d6d, on upstream tip eb19f7b8):
adds SECURITY.md pointing reporters at GitHub private vulnerability reporting
(still disabled upstream - the PR body asks the maintainer to enable it),
scopes in/out for the loopback-only local agent, supported = main. pnpm check
green on the branch. PR creation on HazAT/ultimate is outside credential scope;
user posted it as HazAT/ultimate#86 (confirmed open 2026-11-05).
