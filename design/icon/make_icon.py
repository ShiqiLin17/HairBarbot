"""HairBarbot user-app icon generator (source of design/icon/*.svg|png).

Run: python3 design/icon/make_icon.py   (needs `rsvg-convert`: brew install librsvg)
After changing it, copy the PNGs into design/ios/AppIcon.appiconset/ (AppIcon-light/dark/tinted.png).

HairBarbot user-app icon. Concept: head profile, hair drawn as a fade (contour bands,
long on top -> short at the nape). Writes light / dark / tinted 1024 px SVGs."""
import pathlib, subprocess

OUT = pathlib.Path(__file__).resolve().parent

HEAD = ("M 372 1024 L 372 840 "
        "C 300 790 262 690 262 575 "
        "C 262 375 410 228 585 228 "
        "C 712 228 790 300 812 400 "          # forehead
        "C 820 440 818 470 814 490 "          # brow
        "C 838 535 860 570 864 596 "          # nose
        "C 866 618 852 628 826 630 "          # under nose
        "C 838 660 834 676 826 690 "          # lips
        "C 836 712 832 740 816 760 "          # chin
        "C 790 792 730 800 690 798 "          # jaw
        "L 690 1024 Z")

# hair cap: everything above this curve (hairline at forehead -> behind ear -> nape)
HAIR_CLIP = ("M 0 0 L 1024 0 L 1024 372 L 806 372 "
             "C 735 372 690 410 662 470 "     # hairline -> temple
             "L 640 600 "                     # sideburn
             "C 600 610 540 640 500 700 "     # behind the ear
             "C 470 745 430 790 372 818 "     # down to the nape
             "L 0 818 L 0 1024 Z")

# fade bands: curved stripes sweeping from crown toward nape (each a thick arc)
def bands(colors):
    out = []
    # concentric arcs centred near the ear; outer = crown (longest), inner = nape (shortest)
    cx, cy = 600, 860
    radii = [700, 545, 445, 350]
    for r, c in zip(radii, colors):
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{c}"/>')
    return "\n".join(out)

def svg(bg, head, band_cols, line):
    bg_def = (f'<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
              f'<stop offset="0" stop-color="{bg[0]}"/><stop offset="1" stop-color="{bg[1]}"/></linearGradient>')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
<defs>{bg_def}
<clipPath id="head"><path d="{HEAD}"/></clipPath>
<clipPath id="hair"><path d="{HAIR_CLIP}"/></clipPath>
</defs>
<rect width="1024" height="1024" fill="url(#bg)"/>
<path d="{HEAD}" fill="{head}"/>
<g clip-path="url(#head)"><g clip-path="url(#hair)">
{bands(band_cols)}
</g></g>
</svg>"""

V = {
  # light: barber-blue field, warm-white head, hair fades from deep navy (long) to light blue (short)
  "light":  dict(bg=("#2F6FE0", "#1748B0"), head="#F7F4EE",
                 band_cols=["#0B1F3A", "#183C73", "#2D63B5", "#6E9BE3"], line="#F7F4EE"),
  "dark":   dict(bg=("#121821", "#0A0E14"), head="#E9EEF4",
                 band_cols=["#2F6FE0", "#4F8AF0", "#7FA9F5", "#B5CDF9"], line="#E9EEF4"),
  # tinted: iOS tints a grayscale image -> transparent bg, luminance only
  "tinted": dict(bg=("#000000", "#000000"), head="#FFFFFF",
                 band_cols=["#5A5A5A", "#7C7C7C", "#A0A0A0", "#C6C6C6"], line="#FFFFFF"),
}
for name, kw in V.items():
    svg_path, png_path = OUT / f"icon-{name}.svg", OUT / f"icon-{name}.png"
    svg_path.write_text(svg(**kw))
    subprocess.run(["rsvg-convert", "-w", "1024", "-h", "1024", str(svg_path), "-o", str(png_path)], check=True)
print("ok")
