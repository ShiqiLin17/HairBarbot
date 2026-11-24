# design/: HairBarbot user-app brand resources

This folder holds the colors, app icon and UI rules for the **user-facing HairBarbot app**.
It is **not** for the BarBot developer test app in `ios/BarBot/`, which keeps its plain debug look on purpose.

**Agents and developers: read [`style-guide.md`](style-guide.md) before building any user-facing screen.**

| File | What it is | When to use it |
|---|---|---|
| [`style-guide.md`](style-guide.md) | Color roles, safety color rules, type, layout and don'ts | Read first. You can paste it into a chatbot as a design brief. |
| [`tokens.json`](tokens.json) | **Source of truth** for every color, radius and size (light and dark) | Change values here only |
| [`build_tokens.py`](build_tokens.py) | Generates the platform files below and checks text contrast (stops if any pair is below 4.5:1) | Run `python3 design/build_tokens.py` after editing `tokens.json` |
| [`ios/BrandColors.swift`](ios/BrandColors.swift) | *Generated.* SwiftUI `Color.brand.primary`, `.stop`, `.fadeRamp[i]`…, plus `BrandMetrics` | Copy into the user app's Xcode target |
| [`ios/AppIcon.appiconset/`](ios/AppIcon.appiconset/) | Drop-in Xcode app icon (light, dark and tinted, 1024 px, no alpha) | Replace the target's `Assets.xcassets/AppIcon.appiconset` with it |
| [`web/tokens.css`](web/tokens.css) | *Generated.* CSS custom properties with automatic dark mode | `@import` it in web UIs (for example `pc/live/public`) |
| [`icon/`](icon/) | Icon SVG sources, 1024 px PNGs, `icon-preview.png`, and the generator `make_icon.py` | Edit the icon by changing `make_icon.py`, not the SVGs |

## Rules that are easy to break

1. **Red means safety only.** `stop`, `warn` and `ok` are status colors, not decoration. The brand color is
   blue (`primary`). Never use red, orange or pink as an accent.
2. **No hard-coded hex in app code.** Use `Color.brand.*` or `var(--…)`. Need a new color? Add it to
   `tokens.json` with a `use` note, then regenerate.
3. **Don't edit generated files by hand** (`ios/BrandColors.swift`, `web/tokens.css`). Your changes will be overwritten.
4. **Always pair the fade ramp with numbers.** It is only for hair-length maps, and color alone is never enough.
5. **The STOP button is always visible** while the clipper can run: full width, at least `stopButtonMinHeight` tall.

## Status

- The user-facing app is `ios/BarBot/HairBarbot/`. Its target compiles `ios/BrandColors.swift` in place
  (regenerating updates the app) and uses a copy of `ios/AppIcon.appiconset/`.
- `pc/live/public/common.css` still uses the **old red brand color** (`--accent: #d63a2f`). It has not been
  moved to these tokens yet.
