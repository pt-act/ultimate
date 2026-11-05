# Ultimate: clickjacking and audit findings

**Target:** `HazAT/ultimate` at `e2b9fa6` (2026-11-01). **Status:** still present upstream; fixed in `pt-act/ultimate`.
**Prepared for:** the maintainer of `HazAT/ultimate`.

This is the report that accompanies the remediation branch on `pt-act/ultimate`. It is written to be read on its own:
what the problem is, how to confirm it, what the fix is, and what else the audit found that you may or may not want.

---

## The one finding worth acting on: the UI is clickjackable

Ultimate binds to `127.0.0.1` and gates requests on origin and identity, but it sends **no anti-framing headers**, and
its admission check treats a request with a loopback `Host` and no `Origin` as local. A browser sends no `Origin` for
an iframe, so a page on any origin can frame the UI at `http://127.0.0.1:4747/` and place its own content over it.

The consequence is not a data leak by itself — it is user-driven execution of the agent. The agent runs `bash` with the
operator's privileges in their project directory, so a convincing overlay on the composer is a way to have the user's
own click submit a command.

### Confirming it

Two steps, no special tooling:

```bash
curl -sD- -o /dev/null http://127.0.0.1:4747/ | grep -iE 'frame|content-security'
# no output: no anti-framing header is sent
```

Serve this from any other origin on your machine and load it:

```html
<iframe src="http://127.0.0.1:4747/" style="width:900px;height:700px"></iframe>
```

The UI renders inside the frame. In Chromium you can watch the same thing happen with the response headers visible.

### The cause, precisely

`server/request-security.ts` returns `true` for the loopback branch before it ever consults `Sec-Fetch-*`:

```ts
if (
  !proxied(request.headers) &&
  loopbackAuthority(host, port) &&
  (!origin || loopbackOrigin(origin, port))
)
  return true
```

### The fix

Two layers, because they fail differently:

1. **Headers on every response** (`server/main.ts`): CSP `frame-ancestors`, `X-Frame-Options`, `nosniff`,
   `no-referrer`. `frame-ancestors 'none'` is the obvious choice and is wrong here — `extensions/instance/web.tsx`
   frames another running instance on its own port, a same-site load whose origin differs. The working value names
   the local hosts:

   ```
   frame-ancestors 'self' http://127.0.0.1:* http://localhost:*; object-src 'none'; base-uri 'none'
   ```

2. **Admission refuses the frame itself** (`server/request-security.ts`), so the protection survives a browser that
   does not enforce the header:

   ```ts
   const frame = request.headers['sec-fetch-dest'] === 'iframe'
   if (frame && site === 'cross-site') return false
   ```

   A same-site frame stays admitted (the preview), and a cross-site *root document navigation* stays admitted (a link
   the user followed). Everything else cross-site is refused.

### A trap worth knowing about, because it bit us

The first version of the header listed `http://[::1]:*`. That is **not a valid source expression** — a host source may
not carry a port range with an IPv6 literal — and a browser that meets one unparseable expression drops the **entire**
`frame-ancestors` directive. The header was present on every response and refused nothing. It looked fixed. CI was
green. Only framing the running app in a real browser and reading the console showed it.

If you take one thing from this report: assert the header's *effect*, not its presence.

---

## Two smaller security issues

**The extension-action guard is inverted.** `server/api.ts` rejects only when a request has neither same-origin fetch
metadata nor any `Origin`, so a cross-site request carrying an `Origin` passes it. Today `admit()` stops those, so this
is defence in depth, not an open door — but it is the wrong shape for a guard, and it silently stops protecting the day
`admit()` is relaxed. A positive same-origin check is the fix.

**JSON API responses carry no `Cache-Control`.** The SSE stream sets `no-cache`; the `reply()` helper that serves
everything else sends only `Content-Type`, so conversation history — the user's code and prompts — could land in the
browser's disk cache. `no-store` on `/api/*` is the fix; the rest of Vite's responses should keep their own
revalidation, or a page opened over the tailnet re-downloads the whole app on every reload.

---

## Accessibility: systemic, and measured wrongly by the usual tool

The audit found contrast failures that a token-level check understates. Two things matter for reproducing them:

**Composite the way a browser does.** Opacity-modifier utilities are applied in gamma-encoded sRGB, and a token that
already carries alpha is applied **twice** when a call site adds its own. A linear-light calculation that applies one
alpha reports 2.71:1 where the rendered result is 1.57:1. Our checker (`test/theme-contrast.test.ts`) composites in
gamma space at the rendered alpha.

**The failures, with the values that fix them:**

| What | Was | Now |
|---|---|---|
| `--ring` focus indicator | 1.46:1 light (alpha applied twice) | opaque; 5.02 light, 7.84 dark |
| `--input` border | 1.47 light / 1.38 dark | `L 0.64` / `L 0.50` — 3.22 / 3.14 (3.08 / 3.02 on card) |
| `--muted-foreground` at `/70`–`/80` | 1.79–4.00 | token darkened, opacity modifiers removed |
| light `--success` / `--warning` | 4.33 / 3.89 | `L 0.499` / `L 0.525` |

`text-muted-foreground/NN` cannot be made to pass at any token lightness for the lower steps — a scalar alpha over a
light page tops out around `/80`. Dimming muted text is not a contrast strategy; choose another token.

The focus indicator has a second trap: the base layer applied `outline-ring/50` to every element, which is the fallback
for anything without its own ring. It measured 1.94:1 and was the most common focus path in the app.

**The type scale is in `px`.** 935 `text-[Npx]` utilities and a `font-size: 14px` body ignore both the browser's
default-font-size and minimum-font-size settings: a reader who raises the page font gets the same 8.5–14px type. The
fix is `rem` throughout, and it has three parts that are easy to miss — the utilities, the `leading-[…]` next to them
(a px line-height beside a rem font-size collapses the leading from 1.71 to 1.14 as the page font grows), and the fixed
heights of boxes that hold text.

The one px size to keep is the coarse-pointer rule: below 16px, iOS zooms the page when a field takes focus.

---

## What this is not

No malicious code, telemetry, or unexplained egress was found. The loopback binding, origin and identity checks,
project-extension trust prompt, secret handling, atomic state writes, and locking all reviewed well. The agent running
model-authored commands with the user's privileges is the product, not a vulnerability.

The audit's own correction, for the record: two findings in the first draft were false positives. The conversation
`busy` state has no `await` between its snapshot and write, so there is no race; and `lucide-react` emits
`aria-hidden="true"` by default, so no icon work was needed. Reporting them as fixes would have wasted your time.

---

## What we would like from you

Nothing is expected — this is a personal project and `CONTRIBUTING.md` is clear that most pull requests stay open as
references. Two things would help operators either way:

1. **A `SECURITY.md` and private reporting turned on** (Settings → Code security → Private vulnerability reporting).
   Today a researcher has no private channel, and `CONTRIBUTING.md` says issues are not reviewed.
2. **The anti-framing fix on its own**, if nothing else. It is small, self-contained, and closes the only finding here
   that needs no unusual conditions to exploit — just a user who visits the wrong page.

The full remediation, with tests, is on `pt-act/ultimate` at the merge commit for PR #1. It is yours to take piecemeal,
rework, or ignore.
