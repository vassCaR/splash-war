#!/usr/bin/env python3
"""
Transforme une image en feuille de projection pour le mode cooperatif.

    python scripts/projection.py mon-image.png

Sort projection.png : l'image rendue exactement comme elle apparaitra sur le
plateau, avec les memes reperes tous les huit carreaux et des reperes de
colonnes et de lignes. La salle peut ainsi recopier case par case au lieu de
peindre au jugé.

Le rapprochement de couleur se fait en Lab et non en RVB : la distance y
correspond a ce que l'oeil percoit, ce qui evite qu'un violet et un bleu
proches en RVB se retrouvent confondus.
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = H = 48
BLOC = 8                      # meme subdivision que le plateau
FOND = (26, 13, 82)           # couleur d'une case vide dans le jeu

PALETTE = [
    (1,"VIOLET","#a855f7"),(2,"INDIGO","#4318d4"),(3,"AZUR","#1a67ff"),(4,"CIEL","#4fc3ff"),
    (5,"TURQUOISE","#27eddc"),(6,"JADE","#16c07a"),(7,"ACIDE","#a8f03c"),(8,"OR","#ffc33b"),
    (9,"ORANGE","#ff8a2b"),(10,"BRAISE","#f4402f"),(11,"MAGENTA","#ff069d"),(12,"ROSE","#ff9ad0"),
    (13,"LILAS","#d0a8ff"),(14,"PRUNE","#7b3fb0"),(15,"ARGENT","#c8d2e8"),(16,"NEIGE","#fbf5fd"),
    (17,"MARRON","#8b5a2b"),(18,"CHOCOLAT","#5a3a1c"),(19,"SABLE","#e0c9a0"),(20,"KAKI","#9a9550"),
    (21,"OLIVE","#4f6b1f"),(22,"FORET","#1e7a3c"),(23,"MENTHE","#8ef0b8"),(24,"PIN","#0f5f48"),
    (25,"MARINE","#1d4ea8"),(26,"ARDOISE","#6f8098"),(27,"GRIS","#98a0ad"),(28,"TAUPE","#8a7f6e"),
    (29,"CORAIL","#ff7f6e"),(30,"BORDEAUX","#9c1840"),(31,"BRIQUE","#c25236"),(32,"JAUNE","#fff44f"),
]


def rvb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def lab(c):
    r, g, b = [v / 255 for v in c]
    r, g, b = [((x + .055) / 1.055) ** 2.4 if x > .04045 else x / 12.92 for x in (r, g, b)]
    x = (r * .4124 + g * .3576 + b * .1805) / .95047
    y = (r * .2126 + g * .7152 + b * .0722)
    z = (r * .0193 + g * .1192 + b * .9505) / 1.08883
    f = lambda t: t ** (1 / 3) if t > .008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


LABS = [(i, n, rvb(h), lab(rvb(h))) for i, n, h in PALETTE]


def plus_proche(c):
    cible = lab(c)
    return min(LABS, key=lambda e: math.dist(e[3], cible))


def police(t):
    for c in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(c):
            return ImageFont.truetype(c, t)
    return ImageFont.load_default()


def convertir(chemin, cote=20, marge=60, detourer=True, tolerance=42):
    """
    detourer : les cases proches de la couleur des coins sont laissees vides.

    C'est decisif en pratique. Une photo pleine demande les 2304 cases du
    plateau, soit une quinzaine de MON et bien plus que trois minutes a
    vingt personnes. En detourant, on ne fait peindre que le sujet, et une
    manche cooperative devient jouable.
    """
    im = Image.open(chemin).convert("RGBA")
    c = min(im.size)
    g, haut = (im.width - c) // 2, (im.height - c) // 2
    im = im.crop((g, haut, g + c, haut + c)).resize((W, H), Image.LANCZOS)

    coins = [im.getpixel(c)[:3] for c in ((0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1))]
    fond_img = tuple(sum(k[i] for k in coins) // 4 for i in range(3))

    grille = [[None] * W for _ in range(H)]
    usage = {}
    for y in range(H):
        for x in range(W):
            r, v, b, a = im.getpixel((x, y))
            if a < 110:
                continue
            if detourer and math.dist(lab((r, v, b)), lab(fond_img)) < tolerance:
                continue
            i, nom, rgbv, _ = plus_proche((r, v, b))
            grille[y][x] = rgbv
            usage[nom] = usage.get(nom, 0) + 1

    L = W * cote + marge * 2
    out = Image.new("RGB", (L, L + 120), (8, 4, 30))
    d = ImageDraw.Draw(out)

    for y in range(H):
        for x in range(W):
            px, py = marge + x * cote, marge + y * cote
            d.rectangle([px, py, px + cote - 1, py + cote - 1],
                        fill=grille[y][x] or FOND)

    # Reperes tous les huit carreaux, comme sur le plateau.
    for k in range(0, W + 1, BLOC):
        p = marge + k * cote
        d.line([(p, marge), (p, marge + H * cote)], fill=(180, 140, 255), width=2)
        d.line([(marge, p), (marge + W * cote, p)], fill=(180, 140, 255), width=2)

    f = police(20)
    for k in range(W // BLOC):
        lettre = chr(ord("A") + k)
        d.text((marge + k * BLOC * cote + BLOC * cote // 2 - 7, marge - 30), lettre,
               font=f, fill=(210, 190, 255))
        d.text((marge - 34, marge + k * BLOC * cote + BLOC * cote // 2 - 11), str(k + 1),
               font=f, fill=(210, 190, 255))

    principales = sorted(usage.items(), key=lambda kv: -kv[1])[:8]
    d.text((marge, L + 14), "COULEURS PRINCIPALES : " +
           "   ".join(f"{n} {c}" for n, c in principales),
           font=police(19), fill=(200, 180, 245))
    d.text((marge, L + 52), f"{sum(usage.values())} cases a peindre sur {W*H}",
           font=police(19), fill=(150, 130, 200))

    sortie = os.path.join(ROOT, "projection.png")
    out.save(sortie)
    return sortie, out.size, sum(usage.values()), principales


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage : python scripts/projection.py <image> [--plein] [tolerance]")
    plein = "--plein" in sys.argv
    tol = next((int(a) for a in sys.argv[2:] if a.isdigit()), 42)
    s, taille, n, top = convertir(sys.argv[1], detourer=not plein, tolerance=tol)
    print(f"feuille   {s}  {taille[0]}x{taille[1]}")
    print(f"a peindre {n} cases sur {W*H}")
    cout = n * 0.0065
    print(f"cout      environ {cout:.2f} MON, soit {n/20:.0f} cases par personne a vingt joueurs")
    if n > 900:
        print("ATTENTION : au-dela de 900 cases, une manche de trois minutes a vingt")
        print("            personnes ne suffira pas. Prendre une image plus simple,")
        print("            ou augmenter la tolerance de detourage.")
    print("couleurs  " + ", ".join(f"{a} ({b})" for a, b in top[:6]))
