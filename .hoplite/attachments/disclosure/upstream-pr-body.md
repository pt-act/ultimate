Framing is currently allowed from any origin. `admit()` returns `true` for a loopback `Host` with no `Origin`, and a browser sends no `Origin` for a framed load, so a page on another origin can frame the UI:

```
curl -sD- -o /dev/null http://127.0.0.1:4747/ | grep -iE 'frame|content-security'   # no output
```

Since the agent runs `bash` with the operator's privileges, an overlay on the composer is a way to have the user's own click submit a command.

**What this changes**

- Every response carries `frame-ancestors`, `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`, set before either the API or Vite answers.
- `admit()` refuses a `cross-site` frame before the loopback branch is reached.

`frame-ancestors 'none'` is deliberately not used. `extensions/instance/web.tsx` frames another running instance on its own port — same site, different origin — so the header names loopback instead, and `admit()` keeps admitting both a same-site frame and a cross-site *root navigation* (a link the user followed). Everything else cross-site is refused.

**A trap worth recording, because it produced a false pass here**

`http://[::1]:*` is not a valid source expression — a host source may not carry a port range with an IPv6 literal — and a browser that meets one unparseable expression drops the **whole** `frame-ancestors` directive. The header was present on every response and refused nothing, while every check said it was fixed. Only framing the running app in a browser and reading the console showed it. The test asserts the effect, not the header's presence, and it fails if any source expression stops parsing.

**Verification**

- Framed the running app from another origin in Chromium: refused after this change, rendered before it.
- The instance preview's same-site frame across ports still renders; `test/e2e/instance.test.ts` passes.
- `test/request-security.test.ts` covers the admission truth table, `test/security-headers.test.ts` the header set and its parse rule.

Four files, 165 lines. It is on my fork at `pt-act:upstream/anti-framing`, built on this repository's `main` rather than on my remediation branch, so it contains nothing else.
