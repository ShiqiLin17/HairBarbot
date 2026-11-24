# Notes for AI agents working in this repo

Start with [README.md](README.md) for how the hardware, PC controller and iPhone app fit together.

## UI and visual work
- **User-facing app (any platform):** follow [`design/README.md`](design/README.md) and
  [`design/style-guide.md`](design/style-guide.md). Take colors and sizes from the generated files
  (`design/ios/BrandColors.swift`, `design/web/tokens.css`), never from hex values in prose.
  The app icon is in `design/ios/AppIcon.appiconset/`.
- **Changing a color:** edit `design/tokens.json`, then run `python3 design/build_tokens.py`.
- **Red is reserved for safety** (stop or blade off). Never use it as a brand or accent color.
- **`ios/BarBot/` is the developer test app.** Don't apply the brand style there unless you're asked to.
