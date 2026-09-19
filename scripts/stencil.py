#!/usr/bin/env python3
"""
Gabarits du mode cooperatif : convertit n'importe quelle image en pochoir
48x48 utilisant les 16 couleurs du jeu.

    python scripts/stencil.py image.png "Nom du gabarit"   # convertit une image
    python scripts/stencil.py --motifs                     # (re)genere les motifs fournis

Le resultat va dans web/stencils.json, que le front charge au demarrage.
Le rapprochement de couleur se fait en Lab et non en RVB : deux violets
proches en RVB peuvent etre visuellement distincts, et l'inverse est vrai
aussi. En Lab la distance correspond a ce que l'oeil percoit.
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SORTIE = os.path.join(ROOT, "web", "stencils.json")
W = H = 48

PALETTE = [
    (1, "VIOLET", "#a855f7"), (2, "INDIGO", "#4318d4"), (3, "AZUR", "#1a67ff"),
    (4, "CIEL", "#4fc3ff"), (5, "TURQUOISE", "#27eddc"), (6, "JADE", "#16c07a"),
    (7, "ACIDE", "#a8f03c"), (8, "OR", "#ffc33b"), (9, "ORANGE", "#ff8a2b"),
    (10, "BRAISE", "#f4402f"), (11, "MAGENTA", "#ff069d"), (12, "ROSE", "#ff9ad0"),
    (13, "LILAS", "#d0a8ff"), (14, "PRUNE", "#7b3fb0"), (15, "ARGENT", "#b9c4e8"),
    (16, "NEIGE", "#fbf5fd"),
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


LAB_PALETTE = [(i, lab(rvb(h))) for i, _, h in PALETTE]


def plus_proche(couleur):
    cible = lab(couleur)
    return min(LAB_PALETTE, key=lambda e: math.dist(e[1], cible))[0]


def depuis_image(chemin, nom):
    """Toute image devient un pochoir : recadrage carre, reduction, palettisation."""
    from PIL import Image
    im = Image.open(chemin).convert("RGBA")
    cote = min(im.size)
    g = (im.width - cote) // 2
    haut = (im.height - cote) // 2
    im = im.crop((g, haut, g + cote, haut + cote)).resize((W, H), Image.LANCZOS)

    cells = []
    for y in range(H):
        for x in range(W):
            r, v, b, a = im.getpixel((x, y))
            # Un pixel transparent reste libre : le pochoir n'impose rien la.
            cells.append(0 if a < 110 else plus_proche((r, v, b)))
    return {"nom": nom, "cells": cells}


# ---------------------------------------------------------------------------
# Motifs fournis : dessines ici, geometriques, sans reference exterieure.
# ---------------------------------------------------------------------------

def vide():
    return [0] * (W * H)


def disque(cells, cx, cy, r, couleur):
    for y in range(H):
        for x in range(W):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                cells[y * W + x] = couleur


def losange(cells, cx, cy, r, couleur):
    for y in range(H):
        for x in range(W):
            if abs(x - cx) + abs(y - cy) <= r:
                cells[y * W + x] = couleur


def rectangle(cells, x0, y0, x1, y1, couleur):
    for y in range(max(0, y0), min(H, y1 + 1)):
        for x in range(max(0, x0), min(W, x1 + 1)):
            cells[y * W + x] = couleur


def motif_losange():
    """Le losange du logo, en creux."""
    c = vide()
    losange(c, 24, 24, 19, 2)
    losange(c, 24, 24, 13, 1)
    losange(c, 24, 24, 7, 13)
    losange(c, 24, 24, 3, 16)
    return {"nom": "LOSANGE", "cells": c}


def motif_coeur():
    c = vide()
    disque(c, 17, 18, 9, 11)
    disque(c, 31, 18, 9, 11)
    for y in range(18, 43):
        demi = max(0, 17 - (y - 18) * 17 // 24)
        rectangle(c, 24 - demi, y, 24 + demi, y, 11)
    disque(c, 14, 15, 3, 12)
    return {"nom": "COEUR", "cells": c}


def motif_etoile():
    c = vide()
    import math as m
    pts = []
    for k in range(10):
        ang = -m.pi / 2 + k * m.pi / 5
        rad = 21 if k % 2 == 0 else 8.5
        pts.append((24 + rad * m.cos(ang), 24 + rad * m.sin(ang)))
    for y in range(H):
        croisements = []
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            if (y1 <= y < y2) or (y2 <= y < y1):
                croisements.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        croisements.sort()
        for i in range(0, len(croisements) - 1, 2):
            rectangle(c, int(croisements[i]), y, int(croisements[i + 1]), y, 8)
    return {"nom": "ETOILE", "cells": c}


def motif_smiley():
    c = vide()
    disque(c, 24, 24, 21, 8)
    disque(c, 17, 19, 3, 2)
    disque(c, 31, 19, 3, 2)
    for x in range(14, 35):
        y = 28 + int(6 * math.sin((x - 14) * math.pi / 20))
        rectangle(c, x, y, x, y + 2, 2)
    return {"nom": "SOURIRE", "cells": c}


def motif_damier():
    c = vide()
    for y in range(H):
        for x in range(W):
            c[y * W + x] = 1 if ((x // 6) + (y // 6)) % 2 == 0 else 5
    return {"nom": "DAMIER", "cells": c}


MOTIFS = [motif_losange, motif_coeur, motif_etoile, motif_smiley, motif_damier]


def charger():
    if os.path.exists(SORTIE):
        try:
            return json.load(open(SORTIE))
        except Exception:
            pass
    return {"palette": [{"id": i, "nom": n, "hex": h} for i, n, h in PALETTE],
            "gabarits": []}


def ecrire(data):
    json.dump(data, open(SORTIE, "w"), separators=(",", ":"))
    n = len(data["gabarits"])
    print(f"{n} gabarits dans {os.path.relpath(SORTIE, ROOT)} "
          f"({os.path.getsize(SORTIE) / 1024:.1f} Ko)")
    for g in data["gabarits"]:
        remplies = sum(1 for v in g["cells"] if v)
        print(f"   {g['nom']:<12} {remplies:>5} cases a peindre")


if __name__ == "__main__":
    data = charger()
    if "--motifs" in sys.argv or len(sys.argv) == 1:
        data["gabarits"] = [f() for f in MOTIFS]
    else:
        chemin = sys.argv[1]
        nom = (sys.argv[2] if len(sys.argv) > 2
               else os.path.splitext(os.path.basename(chemin))[0]).upper()[:12]
        data["gabarits"] = [g for g in data["gabarits"] if g["nom"] != nom]
        data["gabarits"].append(depuis_image(chemin, nom))
    ecrire(data)
