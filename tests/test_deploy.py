"""
scripts/deploy.py : compilation et calibration.

La calibration reecrit des constantes dans web/index.html et bot.py par
expression reguliere. Si le front est restructure et que le motif ne colle
plus, la calibration ne fait rien du tout et personne ne s'en apercoit : les
joueurs paient simplement trop cher toute la soiree. Ces tests verifient que
les motifs collent encore.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import deploy  # noqa: E402


def test_compilation():
    abi, bytecode = deploy.compile_contract()
    noms = {f["name"] for f in abi if f["type"] == "function"}
    assert {"claim", "getColors", "getOwners", "endRound", "reset"} <= noms
    assert bytecode and all(c in "0123456789abcdefABCDEF" for c in bytecode)


def test_les_motifs_de_calibration_collent_encore():
    """Un motif qui ne colle plus = calibration silencieusement inoperante."""
    cibles = [
        (os.path.join(ROOT, "web", "index.html"), r"fixed:\s*\d+n"),
        (os.path.join(ROOT, "bot.py"), r"GAS_LIMIT = [\d_]+"),
    ]
    for chemin, motif in cibles:
        with open(chemin) as f:
            contenu = f.read()
        trouves = re.findall(motif, contenu)
        assert len(trouves) == 1, (
            f"{os.path.relpath(chemin, ROOT)} : {len(trouves)} correspondances "
            f"pour {motif}, il en faut exactement une")


def test_injection_de_l_adresse_dans_le_front():
    """Le motif CONTRACT doit exister, sinon l'adresse n'est jamais injectee."""
    with open(os.path.join(ROOT, "web", "index.html")) as f:
        contenu = f.read()
    assert len(re.findall(r'(CONTRACT:\s*)"[^"]*"', contenu)) == 1


def test_le_front_et_le_bot_parlent_du_meme_contrat():
    """L'ABI du front doit correspondre aux fonctions reellement compilees."""
    abi, _ = deploy.compile_contract()
    onchain = {f["name"] for f in abi if f["type"] == "function"}
    with open(os.path.join(ROOT, "web", "index.html")) as f:
        front = f.read()
    appelees = set(re.findall(r'"function (\w+)\(', front))
    manquantes = appelees - onchain
    assert not manquantes, f"le front appelle des fonctions inexistantes : {manquantes}"


def test_structure_html_equilibree():
    """
    Une balise fermante en trop referme un conteneur trop tot : le reste de la
    page sort de sa colonne et part en pleine largeur. Le navigateur ne signale
    rien, la page se charge, et le defaut ne se voit qu'a l'oeil.
    C'est exactement ce qui est arrive en deplacant un bloc d'une colonne a
    l'autre. Ce test l'attrape sans avoir a regarder une capture.
    """
    from html.parser import HTMLParser

    class Verificateur(HTMLParser):
        AUTOFERMANTES = {"br", "img", "input", "meta", "link", "hr", "source"}

        def __init__(self):
            super().__init__()
            self.pile, self.problemes = [], []

        def handle_starttag(self, tag, attrs):
            if tag not in self.AUTOFERMANTES:
                self.pile.append((tag, self.getpos()[0]))

        def handle_endtag(self, tag):
            if tag in self.AUTOFERMANTES:
                return
            if not self.pile:
                self.problemes.append(f"ligne {self.getpos()[0]} : </{tag}> sans ouverture")
                return
            ouvert, ligne = self.pile.pop()
            if ouvert != tag:
                self.problemes.append(
                    f"ligne {self.getpos()[0]} : </{tag}> ferme <{ouvert}> ouvert ligne {ligne}")

    v = Verificateur()
    with open(os.path.join(ROOT, "web", "index.html")) as f:
        v.feed(f.read())

    assert not v.problemes, "structure HTML incoherente :\n  " + "\n  ".join(v.problemes)
    assert not v.pile, "balises jamais fermees : " + str(v.pile)
