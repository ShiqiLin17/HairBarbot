# HairBarbot user app: color and style guide

> **For code:** the hex values below come from [`tokens.json`](tokens.json), which is the source of truth.
> In code, use the generated files: `Color.brand.*` from [`ios/BrandColors.swift`](ios/BrandColors.swift),
> or `var(--…)` from [`web/tokens.css`](web/tokens.css). Don't paste hex values. If this guide and
> `tokens.json` ever disagree, `tokens.json` wins.

Use this guide for every screen of the HairBarbot consumer app (iPhone, SwiftUI). HairBarbot is a handheld
clipper. The user rolls it over their own head, and the app picks the hair length for each spot.
The app must feel **calm, precise and trustworthy**: a safety-critical tool, not a toy.
The look is clean and modern, with a quiet nod to barbershops (the blue of the barber pole).

## Rule 1: red is reserved for safety
Red means only one thing in this app: **stop, the blade is off, or danger.** Never use red for branding,
decoration, selected tabs, badges or "sale" accents. If a user sees red, it must be because something
needs their attention right now. Amber and green follow the same rule (see Status colors).

## Brand colors
| Token | Light | Dark | Use |
|---|---|---|---|
| `primary` | `#1F5FD6` | `#4F8AF0` | Main buttons, links, selected states, progress |
| `primaryPressed` | `#1748B0` | `#7FA9F5` | Pressed or active state of primary |
| `onPrimary` | `#FFFFFF` | `#0A0E14` | Text and icons on `primary` |
| `navy` | `#0B1F3A` | `#0B1F3A` | Hero headers, onboarding backgrounds, icon field |
| `warmWhite` | `#F7F4EE` | (not used) | Occasional warm surface (onboarding, success cards) |

## Neutrals
| Token | Light | Dark | Use |
|---|---|---|---|
| `bg` | `#F4F6F9` | `#0A0E14` | Screen background |
| `surface` | `#FFFFFF` | `#121821` | Cards, sheets |
| `surface2` | `#EEF1F5` | `#1A222D` | Inset areas, segmented controls |
| `ink` | `#0E1620` | `#E9EEF4` | Main text |
| `muted` | `#5B6673` | `#8C99A8` | Secondary text, captions |
| `line` | `#DCE2E8` | `#263040` | Dividers, card borders |

## Status colors (functional only)
| Token | Light | Dark | Meaning |
|---|---|---|---|
| `stop` | `#D92D20` | `#FF453A` | Blade off, emergency stop, error. The STOP button. |
| `onStop` | `#FFFFFF` | `#1A0503` | Text on `stop` |
| `warn` | `#B54708` | `#F5A524` | Wait or adjust (rollers still moving, move slower, low battery) |
| `ok` | `#1E7F4C` | `#3DD68C` | Ready to cut, area done, connected |

Put text on `stop` in `onStop`: white in light mode, `#1A0503` in dark mode (white on `#FF453A` fails contrast).

## Fade ramp (hair-length maps only)
Use this ramp for head maps and length legends: dark means longer hair, light means shorter.
It matches the app icon.
`#0B1F3A` (longest) → `#183C73` → `#2D63B5` → `#6E9BE3` → `#B5CDF9` (shortest)
Show the length in mm or cm next to the colors. Never use color alone.
Mark areas already cut with a pattern or outline, not with green fills (green means "ready").

## Contrast (checked, WCAG)
- White on `primary` `#1F5FD6`: 5.7:1. `ink` on `bg`: 16.8:1. `muted` on `bg`: 5.4:1.
- Dark: `ink` on `bg` 16.6:1. `muted` on `surface` 6.1:1. `primary` on `bg` 5.7:1.
- Keep all body text at 4.5:1 or higher. Do not add colors that fall below that.

## Typography and shape
- Font: SF Pro (system). Use SF Mono or tabular numbers for lengths, distances and timers.
- Lengths in large type during a cut (for example "2.0 cm"), so they're readable at arm's length in a mirror.
- Corner radius: 14 pt for cards, 16 pt for big buttons, full pill for chips.
- Icons: SF Symbols, regular weight, in `ink` or `primary`.
- Few shadows. Separate cards with color and 1 pt `line` borders.

## Layout rules
- The **STOP button is always visible** while the clipper can run: full width, fixed at the bottom,
  `stop` background, at least 56 pt tall, bold uppercase "STOP".
- One primary action per screen. Secondary actions are plain text or outline buttons in `primary`.
- Support light and dark mode with the tokens above. Never hard-code a color outside this list.
- Respect Reduce Motion: no blinking or pulsing unless it's a safety alert, and turn that off too
  when Reduce Motion is on (use a solid color instead).

## App icon
Side view of a head, with the hair drawn as a fade: dark navy bands on the crown get lighter down to the nape.
It sits on a barber-blue gradient (`#2F6FE0` → `#1748B0`), and the head is `#F7F4EE`.
There are three versions: light, dark (navy-black field with blue bands) and tinted (grayscale).
The sources are in [`icon/`](icon/), and a drop-in Xcode icon set is in [`ios/AppIcon.appiconset/`](ios/AppIcon.appiconset/).

## Don'ts
- No red, pink or orange as brand or accent colors.
- No barber-pole stripes in red and white anywhere in the UI.
- No gradients on buttons or text. Use gradients only on the icon and the onboarding hero.
- No neon colors, glow effects or "techy" HUD styles. This is a personal-care product.
