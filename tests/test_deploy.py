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
