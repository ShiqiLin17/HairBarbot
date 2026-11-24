"""Generate platform color files from design/tokens.json.

    python3 design/build_tokens.py

Writes:
  design/ios/BrandColors.swift   SwiftUI `Color.brand.*` with automatic light/dark
  design/web/tokens.css          CSS custom properties with a prefers-color-scheme dark block
Also checks WCAG contrast for the text/background pairs the app relies on and fails if one drops below 4.5:1.
"""
import json, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
T = json.loads((HERE / "tokens.json").read_text())
C = T["color"]
HEADER = "GENERATED from design/tokens.json by design/build_tokens.py. Do not edit by hand."

def rgb(h):
    h = h.lstrip("#"); return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]

def lum(h):
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = map(f, rgb(h)); return 0.2126 * r + 0.7152 * g + 0.0722 * b

def contrast(a, b):
    x, y = sorted([lum(a), lum(b)]); return (y + 0.05) / (x + 0.05)

def kebab(s): return re.sub(r"(?<!^)(?=[A-Z0-9])", "-", s).lower()

# ---- contrast gate -------------------------------------------------------------------
PAIRS = [("ink", "bg"), ("ink", "surface"), ("muted", "bg"), ("muted", "surface"),
         ("onPrimary", "primary"), ("onStop", "stop"), ("primary", "surface")]
bad = []
for fg, bg in PAIRS:
    for mode in ("light", "dark"):
        r = contrast(C[fg][mode], C[bg][mode])
        if r < 4.5: bad.append(f"{fg} on {bg} ({mode}): {r:.2f}:1")
if bad:
    sys.exit("Contrast below 4.5:1:\n  " + "\n  ".join(bad))

# ---- Swift ---------------------------------------------------------------------------
def sw(h):
    r, g, b = rgb(h); return f"UIColor(red: {r:.4f}, green: {g:.4f}, blue: {b:.4f}, alpha: 1)"

lines = [f"// {HEADER}", "// Use: Color.brand.primary, Color.brand.stop, Color.brand.fadeRamp[0] ...", "",
         "import SwiftUI", "import UIKit", "",
         "private func dynamic(_ light: UIColor, _ dark: UIColor) -> Color {",
         "    Color(UIColor { $0.userInterfaceStyle == .dark ? dark : light })", "}", "",
         "struct BrandColors {"]
for name, v in C.items():
    lines.append(f"    /// {v['use']}")
    lines.append(f"    let {name} = dynamic({sw(v['light'])}, {sw(v['dark'])})")
ramp = ", ".join(f"Color({sw(h)})" for h in T["fadeRamp"]["stops"])
lines += [f"    /// {T['fadeRamp']['use']}", f"    let fadeRamp: [Color] = [{ramp}]", "}", "",
          "enum BrandMetrics {"]
for k, v in T["radius"].items(): lines.append(f"    static let {k}Radius: CGFloat = {v}")
for k, v in T["size"].items(): lines.append(f"    static let {k}: CGFloat = {v}")
lines += ["}", "", "extension Color {", "    static let brand = BrandColors()", "}", ""]
(HERE / "ios" / "BrandColors.swift").write_text("\n".join(lines))

# ---- CSS -----------------------------------------------------------------------------
css = [f"/* {HEADER} */", ":root {"]
for n, v in C.items(): css.append(f"  --{kebab(n)}: {v['light']};  /* {v['use']} */")
for i, h in enumerate(T["fadeRamp"]["stops"]): css.append(f"  --fade-{i}: {h};")
for k, v in T["radius"].items(): css.append(f"  --radius-{kebab(k)}: {v}px;")
css.append(f"  --stop-button-min-height: {T['size']['stopButtonMinHeight']}px;")
css.append(f"  --sans: {T['font']['web']['text']};")
css.append(f"  --mono: {T['font']['web']['numbers']};")
css += ["}", "@media (prefers-color-scheme: dark) {", "  :root {", "    color-scheme: dark;"]
for n, v in C.items(): css.append(f"    --{kebab(n)}: {v['dark']};")
css += ["  }", "}", ""]
(HERE / "web" / "tokens.css").write_text("\n".join(css))
print("wrote ios/BrandColors.swift and web/tokens.css; contrast OK")
