#!/usr/bin/env python3
"""
Rend le front dans un chassis de telephone, pour juger du resultat et pour la demo.

    .venv/bin/python scripts/mockup_phone.py "<url>" [sortie.png]
"""
import os, sys
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LARG, HAUT, DPR = 390, 844, 2              # gabarit d'un telephone courant


def capture(url, chemin, cle=None, couleur=None):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": LARG, "height": HAUT},
                        device_scale_factor=DPR, is_mobile=True, has_touch=True)
        if cle:
            pg.add_init_script(f"localStorage.setItem('tw.pk','{cle}');"
                               f"localStorage.setItem('tw.color','{couleur or 11}');")
        pg.goto(url, wait_until="networkidle")
        pg.wait_for_timeout(4000)
        pg.screenshot(path=chemin)
        b.close()


def chassis(capture_png, sortie):
    """Coque, encoche, bouton : de quoi se projeter dans la main du joueur."""
    ecran = Image.open(capture_png).convert("RGB")
    ecran = ecran.resize((LARG * 2, HAUT * 2), Image.LANCZOS)
    l, h = ecran.size

    marge, rayon = 26, 62
    img = Image.new("RGB", (l + marge * 2, h + marge * 2), (8, 4, 26))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], rayon + 14,
                        fill=(22, 12, 48), outline=(70, 40, 140), width=5)
    d.rounded_rectangle([marge - 4, marge - 4, marge + l + 3, marge + h + 3],
                        rayon, fill=(0, 0, 0))

    masque = Image.new("L", (l, h), 0)
    ImageDraw.Draw(masque).rounded_rectangle([0, 0, l - 1, h - 1], rayon, fill=255)
    img.paste(ecran, (marge, marge), masque)

    # encoche et bouton lateral
    ln = int(l * 0.34)
    d.rounded_rectangle([marge + (l - ln) // 2, marge, marge + (l + ln) // 2, marge + 46],
                        22, fill=(0, 0, 0))
    d.rounded_rectangle([img.width - 5, marge + 260, img.width - 1, marge + 420],
                        3, fill=(70, 40, 140))

    img.thumbnail((620, 1400), Image.LANCZOS)
    img.save(sortie)
    return img.size


if __name__ == "__main__":
    url = sys.argv[1]
    sortie = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "mockup-telephone.png")
    brut = "/tmp/claude-1000/-home-jean-dev-monad-blitz/cc002d3c-5e76-41e8-a0e4-efa01c1ee78f/scratchpad/phone-raw.png"
    capture(url, brut, os.environ.get("TW_DEMO_KEY"), os.environ.get("TW_DEMO_COLOR"))
    print("mockup", chassis(brut, sortie), "->", sortie)
