"""
Les invariants qui sont l'argument technique du pitch.

Si l'un de ces tests casse, ce n'est pas un detail d'implementation : c'est la
these du projet qui tombe. Ils sont ecrits pour echouer bruyamment si quelqu'un
ajoute un compteur global "juste pour le leaderboard".
"""
import os
import re
from web3 import Web3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONT = os.path.join(ROOT, "web", "index.html")
NB_SLOTS_FIXES = 8          # on surveille largement au-dela des slots declares


def slots(w3, address, n=NB_SLOTS_FIXES):
    """Photo des n premiers slots de storage du contrat."""
    return [w3.eth.get_storage_at(address, i) for i in range(n)]


def test_aucune_ecriture_globale_pendant_une_pose(w3, tw, accounts):
    """
    LE test du projet.

    Les slots fixes du contrat (epoch, cooldown, admin, et les racines des
    mappings) ne doivent pas bouger d'un iota quand un joueur pose une case.
    Une pose n'ecrit que deux emplacements, tous deux derives d'un hash :
    celui de la case, et celui du joueur. Aucun slot partage, donc rien
    n'oblige deux poses concurrentes a s'executer l'une apres l'autre.

    Un simple totalClaims++ ferait echouer ce test, et ferait passer toutes
    les transactions du jeu par un seul slot.
    """
    avant = slots(w3, tw.address)
    tw.functions.claim(511, 7).transact({"from": accounts[1]})
    apres = slots(w3, tw.address)
    assert avant == apres, "une pose a modifie un slot global"

    # et cela reste vrai pour des joueurs differents sur des cases differentes
    for i, compte in enumerate(accounts[1:6], start=1):
        tw.functions.claim(i * 37, (i % 32) + 1).transact({"from": compte})
    assert slots(w3, tw.address) == avant, "une pose a modifie un slot global"


def test_deux_joueurs_deux_cases_aucun_etat_commun(w3, tw, accounts):
    """
    Deux poses sur deux cases par deux joueurs touchent quatre emplacements
    deux a deux disjoints. On le verifie en relisant l'etat : chacun garde
    exactement sa case et son compteur, aucune interference.
    """
    a, b = accounts[1], accounts[2]
    tw.functions.claim(100, 1).transact({"from": a})
    tw.functions.claim(900, 9).transact({"from": b})

    owners = tw.functions.getOwners().call()
    colors = tw.functions.getColors().call()
    assert owners[100] == a and colors[100] == 1
    assert owners[900] == b and colors[900] == 9
    assert tw.functions.claimsOf(a).call() == 1
    assert tw.functions.claimsOf(b).call() == 1


def test_reset_est_une_seule_ecriture(w3, tw, accounts, admin):
    """Le reset ne doit toucher qu'un slot : le compteur de manche."""
    for cell in range(50):
        tw.functions.claim(cell, 2).transact({"from": accounts[1]})

    avant = slots(w3, tw.address)
    tw.functions.reset().transact({"from": admin})
    apres = slots(w3, tw.address)

    differents = [i for i, (x, y) in enumerate(zip(avant, apres)) if x != y]
    assert len(differents) == 1, f"reset a touche {len(differents)} slots : {differents}"


def test_la_cagnotte_ne_touche_pas_le_chemin_chaud(w3, tw, accounts):
    """
    Le systeme de recompense a le droit d'ecrire du storage global, mais
    seulement a l'abondement et a la cloture. Une pose ne doit jamais le faire,
    meme quand la cagnotte est pleine.
    """
    w3.eth.send_transaction({"from": accounts[5], "to": tw.address,
                             "value": Web3.to_wei(5, "ether")})
    avant = slots(w3, tw.address)
    tw.functions.claim(333, 11).transact({"from": accounts[1]})
    assert slots(w3, tw.address) == avant
    assert tw.functions.prizePool().call() == Web3.to_wei(5, "ether")


# ---------------------------------------------------------------------------
# Gas : Monad facture la limite, donc chaque millier de marge est paye par
# tout le monde. Ces tests mesurent le cout reel et verifient que les
# constantes du front le couvrent sans exces.
# ---------------------------------------------------------------------------

def constantes_du_front():
    """Lit les constantes de gas directement dans web/index.html."""
    with open(FRONT) as f:
        html = f.read()
    bloc = re.search(r"GAS:\s*\{(.*?)\}", html, re.S).group(1)
    return {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)n", bloc)}


def limite_du_front(case_chaude, joueur_chaud):
    """Reproduit exactement le calcul de gasFor() cote front."""
    g = constantes_du_front()
    case = g["warm"] if case_chaude else g["cold"]
    joueur = g["warm"] if joueur_chaud else g["cold"]
    return (g["fixed"] + case + joueur) * g["margin"] // 100


def mesures(w3, tw, accounts):
    """Les trois situations reelles, du pire cas au cas courant."""
    a, b = accounts[1], accounts[2]
    r = {}
    r["vierge_vierge"] = w3.eth.wait_for_transaction_receipt(
        tw.functions.claim(0, 1).transact({"from": a})).gasUsed
    r["vierge_chaud"] = w3.eth.wait_for_transaction_receipt(
        tw.functions.claim(1, 1).transact({"from": a})).gasUsed
    r["chaud_vierge"] = w3.eth.wait_for_transaction_receipt(
        tw.functions.claim(0, 2).transact({"from": b})).gasUsed
    r["chaud_chaud"] = w3.eth.wait_for_transaction_receipt(
        tw.functions.claim(1, 3).transact({"from": b})).gasUsed
    return r


def test_cout_reel_dune_pose(w3, tw, accounts):
    m = mesures(w3, tw, accounts)
    print("\n  cout mesure d'une pose :")
    for nom, gas in m.items():
        print(f"    {nom:16s} {gas:6d} gas")

    # le pire cas doit rester sous la limite de bloc d'un gros bloc Monad
    assert m["vierge_vierge"] < 100_000
    # une repeinture doit etre nettement moins chere qu'une case vierge,
    # sinon le gas adaptatif du front ne sert a rien
    assert m["chaud_chaud"] < m["vierge_vierge"] * 0.65


def test_le_front_couvre_le_cout_reel(w3, tw, accounts):
    """
    La limite envoyee par le front doit couvrir la depense.

    Attention a la reference : les constantes du front sont calibrees sur
    Monad, qui consomme nettement plus que l'EVM de reference pour le meme
    code. Mesure au deploiement : 90330 gas dans le pire cas sur le testnet
    Monad, contre environ 71600 ici. Environ 26 pour cent d'ecart.

    On verifie donc deux choses distinctes :
      - la limite couvre toujours le cout local, sinon elle ne couvrirait
        rien nulle part ;
      - elle ne depasse pas le cout Monad connu de plus de 45 pour cent,
        parce que c'est la chaine reellement visee et que Monad facture la
        limite. Mesurer la marge contre l'EVM local ferait echouer le test
        pour une bonne calibration, ou pire, le ferait passer pour une
        mauvaise.
    """
    MONAD_PIRE_CAS = 90330      # mesure sur testnet au deploiement
    m = mesures(w3, tw, accounts)
    cas = [
        ("vierge_vierge", False, False),
        ("vierge_chaud",  False, True),
        ("chaud_vierge",  True,  False),
        ("chaud_chaud",   True,  True),
    ]
    print("\n  limite du front contre cout local :")
    for nom, case_chaude, joueur_chaud in cas:
        limite = limite_du_front(case_chaude, joueur_chaud)
        reel = m[nom]
        print(f"    {nom:16s} local {reel:6d}  limite {limite:6d}")
        assert limite >= reel, f"{nom} : le front enverrait {limite}, il en faut {reel}"

    pire = limite_du_front(False, False)
    marge = (pire - MONAD_PIRE_CAS) / MONAD_PIRE_CAS * 100
    print(f"    pire cas Monad {MONAD_PIRE_CAS}  limite {pire}  marge {marge:+.1f} %")
    assert pire >= MONAD_PIRE_CAS, (
        f"la limite {pire} ne couvre pas le pire cas Monad {MONAD_PIRE_CAS} : "
        "chaque transaction mourrait en OutOfGas, payee et perdue")
    assert marge < 45, f"{marge:.0f} % de marge sur Monad, c'est paye pour rien"


def test_la_lecture_du_plateau_reste_gratuite(w3, tw, accounts):
    """
    getColors et getOwners sont des vues : elles doivent rester appelables
    meme plateau plein, sinon le front se fige pendant la demo.
    """
    for cell in range(0, 2304, 13):
        tw.functions.claim(cell, (cell % 32) + 1).transact({"from": accounts[1]})
    assert len(tw.functions.getColors().call()) == 2304
    assert len(tw.functions.getOwners().call()) == 2304
    assert sum(tw.functions.colorScores().call()) == len(range(0, 2304, 13))


def test_identite_hors_du_chemin_chaud(w3, tw, accounts):
    """
    Pseudo et destination de gains sont deux ecritures de plus dans le
    contrat. Elles ne doivent rien changer a une pose : ni slot fixe modifie,
    ni cout supplementaire.
    """
    a = accounts[1]
    tw.functions.setName(b"MARTIN".ljust(32, b"\x00")).transact({"from": a})
    tw.functions.setPayout(accounts[7]).transact({"from": a})

    avant = slots(w3, tw.address)
    tw.functions.claim(200, 5).transact({"from": a})
    assert slots(w3, tw.address) == avant, "une pose a modifie un slot global"


def test_le_pseudo_ne_renchérit_pas_la_pose(w3, tw, accounts):
    """Le cout d'une pose doit etre le meme avec et sans pseudo declare."""
    a, b = accounts[1], accounts[2]
    tw.functions.setName(b"AVEC".ljust(32, b"\x00")).transact({"from": a})

    tw.functions.claim(0, 1).transact({"from": a})       # rechauffe les deux slots
    tw.functions.claim(1, 1).transact({"from": b})
    avec = w3.eth.wait_for_transaction_receipt(
        tw.functions.claim(0, 2).transact({"from": a})).gasUsed
    sans = w3.eth.wait_for_transaction_receipt(
        tw.functions.claim(1, 2).transact({"from": b})).gasUsed
    assert abs(avec - sans) < 100, (avec, sans)
