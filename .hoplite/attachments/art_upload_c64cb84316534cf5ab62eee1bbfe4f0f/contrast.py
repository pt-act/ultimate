#!/usr/bin/env python3
"""WCAG contrast ratios for Ultimate's oklch design tokens."""
import math

def oklch_to_linear_srgb(L, C, H):
    h = math.radians(H)
    a = C * math.cos(h)
    b = C * math.sin(h)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_**3, m_**3, s_**3
    r =  4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return [min(1.0, max(0.0, v)) for v in (r, g, bl)]

def luminance(L, C, H):
    r, g, b = oklch_to_linear_srgb(L, C, H)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def blend(fg, bg, alpha):
    """Composite fg (linear rgb list) over bg with alpha, return linear rgb."""
    return [f * alpha + b * (1 - alpha) for f, b in zip(fg, bg)]

def ratio(l1, l2):
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)

DARK = {
    'background': (0.178, 0.003, 270),
    'foreground': (0.87, 0.004, 270),
    'card': (0.2, 0.004, 270),
    'popover': (0.205, 0.004, 270),
    'secondary': (0.235, 0.005, 270),
    'muted': (0.235, 0.005, 270),
    'muted-foreground': (0.64, 0.01, 270),
    'accent': (0.255, 0.006, 270),
    'destructive': (0.66, 0.18, 25),
    'border': (0.275, 0.005, 270),
    'input': (0.3, 0.006, 270),
    'brand': (0.75, 0.13, 300),
    'brand-foreground': (0.2, 0.03, 300),
    'success': (0.76, 0.14, 155),
    'warning': (0.82, 0.13, 80),
    'note': (0.85, 0.09, 95),
    'error': (0.7, 0.17, 25),
    'diff-add': (0.78, 0.14, 160),
    'diff-del': (0.72, 0.16, 25),
    'terminal': (0.155, 0.003, 270),
    'sidebar': (0.165, 0.003, 270),
}
LIGHT = {
    'background': (0.985, 0.002, 270),
    'foreground': (0.22, 0.006, 270),
    'card': (0.97, 0.003, 270),
    'popover': (0.995, 0.001, 270),
    'secondary': (0.94, 0.004, 270),
    'muted': (0.945, 0.004, 270),
    'muted-foreground': (0.5, 0.012, 270),
    'accent': (0.93, 0.005, 270),
    'destructive': (0.56, 0.19, 25),
    'border': (0.9, 0.005, 270),
    'input': (0.86, 0.006, 270),
    'brand': (0.52, 0.18, 300),
    'brand-foreground': (0.98, 0.01, 300),
    'success': (0.55, 0.14, 155),
    'warning': (0.6, 0.14, 70),
    'note': (0.74, 0.11, 92),
    'error': (0.56, 0.19, 25),
    'diff-add': (0.5, 0.14, 160),
    'diff-del': (0.53, 0.18, 25),
    'terminal': (0.955, 0.003, 270),
    'sidebar': (0.965, 0.003, 270),
}

PAIRS = [
    ('foreground', 'background', 'body text'),
    ('foreground', 'card', 'body text on card'),
    ('foreground', 'popover', 'body text in popover'),
    ('foreground', 'secondary', 'body text on secondary'),
    ('foreground', 'muted', 'body text on muted'),
    ('foreground', 'accent', 'body text on accent'),
    ('foreground', 'sidebar', 'body text in sidebar'),
    ('muted-foreground', 'background', 'muted text (10.5-12px in many places)'),
    ('muted-foreground', 'card', 'muted text on card'),
    ('muted-foreground', 'muted', 'muted text on muted chip'),
    ('muted-foreground', 'secondary', 'muted text on secondary'),
    ('muted-foreground', 'popover', 'muted text in popover'),
    ('muted-foreground', 'sidebar', 'muted text in sidebar'),
    ('brand', 'background', 'brand link/text'),
    ('brand', 'card', 'brand link on card'),
    ('brand', 'popover', 'brand link in popover'),
    ('brand', 'muted', 'brand text on muted'),
    ('success', 'background', 'success text'),
    ('success', 'card', 'success text on card'),
    ('warning', 'background', 'warning text'),
    ('warning', 'card', 'warning text on card'),
    ('error', 'background', 'error text'),
    ('error', 'card', 'error text on card'),
    ('destructive', 'background', 'destructive text'),
    ('diff-add', 'background', 'diff added text'),
    ('diff-del', 'background', 'diff removed text'),
    ('note', 'background', 'note text'),
    ('border', 'background', 'BORDER / control outline (needs 3:1)'),
    ('border', 'card', 'BORDER on card (needs 3:1)'),
    ('input', 'background', 'INPUT border (needs 3:1)'),
    ('input', 'card', 'INPUT border on card (needs 3:1)'),
    ('accent', 'background', 'ACCENT bg as control fill (needs 3:1)'),
    ('secondary', 'background', 'SECONDARY bg as control fill (needs 3:1)'),
    ('muted', 'background', 'MUTED bg as control fill (needs 3:1)'),
    ('brand', 'card', 'BRAND as control fill on card (needs 3:1)'),
]

def report(name, tokens):
    print(f'\n=== {name} ===')
    lum = {k: luminance(*v) for k, v in tokens.items()}
    for fg, bg, label in PAIRS:
        if fg not in tokens or bg not in tokens:
            continue
        r = ratio(lum[fg], lum[bg])
        need = 3.0 if 'needs 3:1' in label else 4.5
        flag = 'FAIL' if r < need else ('near' if r < need + 0.4 else 'ok')
        print(f'{r:6.2f}  [{need}] {flag:4}  {fg} on {bg} — {label}')

report('DARK (default)', DARK)
report('LIGHT', LIGHT)

# focus ring: oklch(0.74 0.13 300 / 0.5) over background
for name, tokens, ring in (('DARK', DARK, (0.74, 0.13, 300, 0.5)), ('LIGHT', LIGHT, (0.55, 0.17, 300, 0.55))):
    bg = tokens['background']
    bgl = oklch_to_linear_srgb(*bg)
    rl = blend(oklch_to_linear_srgb(ring[0], ring[1], ring[2]), bgl, ring[3])
    rlum = 0.2126*rl[0] + 0.7152*rl[1] + 0.0722*rl[2]
    bglum = luminance(*bg)
    print(f'\n{name} focus ring over background: {ratio(rlum, bglum):.2f} (needs 3:1 for a focus indicator)')
