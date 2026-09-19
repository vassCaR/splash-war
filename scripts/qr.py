#!/usr/bin/env python3
"""
Genere le QR code que la salle scanne, et l'affiche pretes a projeter.

    python scripts/qr.py https://splash-war.vercel.app/?contract=0x...

Sort deux fichiers : un QR nu (impression, ecran) et une affiche complete
avec le logo, prete a projeter au videoprojecteur pendant le pitch.
"""
import sys, os
import qrcode
from qrcode.constants import ERROR_CORRECT_H
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIOLET, FOND, CLAIR = (107, 31, 219), (1, 0, 16), (239, 204, 247)


def police(taille):
    for chemin in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(chemin):
            return ImageFont.truetype(chemin, taille)
    return ImageFont.load_default()


def generer(url, sortie_qr, sortie_affiche):
    # Correction haute : un QR projete ou imprime prend des reflets et des plis.
    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_H,
                       box_size=18, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    # Polarite standard : modules sombres sur fond clair. Un QR inverse est
    # lu par la plupart des telephones, mais pas par tous, et on ne peut pas
    # se permettre qu'une personne sur dix reste bloquee devant l'ecran.
    img = qr.make_image(fill_color="#1a0533", back_color="#ffffff").convert("RGB")
    img.save(sortie_qr)

    # Affiche 1080x1500, lisible a plusieurs metres.
    L, H = 1080, 1500
    aff = Image.new("RGB", (L, H), FOND)
    d = ImageDraw.Draw(aff)
    d.rectangle([0, 0, L, 8], fill=VIOLET)
    d.rectangle([0, H - 8, L, H], fill=VIOLET)

    y = 70
    wm = os.path.join(ROOT, "web", "wordmark.png")
    if os.path.exists(wm):
        logo = Image.open(wm).convert("RGBA")
        logo.thumbnail((760, 300), Image.LANCZOS)
        aff.paste(logo, ((L - logo.width) // 2, y), logo)
        y += logo.height + 50

    # Marge blanche large autour du QR : la zone de silence fait partie du
    # standard, sans elle les lecteurs accrochent mal.
    q = img.resize((700, 700), Image.NEAREST)
    cadre = Image.new("RGB", (780, 780), "#ffffff")
    cadre.paste(q, (40, 40))
    aff.paste(cadre, ((L - 780) // 2, y))
    y += 820

    for texte, taille, couleur in (("SCANNE ET PEINS", 58, CLAIR),
                                   ("une case = une transaction onchain", 30, (168, 89, 242)),
                                   ("monad testnet - aucune appli a installer", 26, (143, 120, 196))):
        f = police(taille)
        larg = d.textbbox((0, 0), texte, font=f)[2]
        d.text(((L - larg) // 2, y), texte, font=f, fill=couleur)
        y += taille + 22

    aff.save(sortie_affiche)
    return img.size, aff.size


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080/"
    os.makedirs(os.path.join(ROOT, "web"), exist_ok=True)
    a = os.path.join(ROOT, "web", "qr.png")
    b = os.path.join(ROOT, "affiche-qr.png")
    t1, t2 = generer(url, a, b)
    print(f"url      {url}")
    print(f"qr       {a}  {t1[0]}x{t1[1]}")
    print(f"affiche  {b}  {t2[0]}x{t2[1]}")
