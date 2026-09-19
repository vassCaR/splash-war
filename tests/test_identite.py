"""
Pseudo et destination des gains.

Ces deux ecritures existent pour la demo : un classement en hexadecimal ne
veut rien dire au videoprojecteur, et un wallet jetable qui vit dans un
localStorage est un mauvais endroit ou laisser une recompense.

Elles sont facultatives et hors du chemin chaud. test_invariants.py verifie
que claim() ne les touche pas.
"""
from web3 import Web3
from conftest import expect_revert

ZERO = "0x" + "00" * 20


def b32(texte):
    return texte.encode().ljust(32, b"\x00")


def lisible(brut):
    return brut.rstrip(b"\x00").decode()


def test_pseudo(tw, accounts):
    a = accounts[1]
    assert tw.functions.names(a).call() == b"\x00" * 32     # vide par defaut

    tw.functions.setName(b32("MARTIN")).transact({"from": a})
    assert lisible(tw.functions.names(a).call()) == "MARTIN"


def test_pseudo_modifiable(tw, accounts):
    a = accounts[1]
    tw.functions.setName(b32("MARTIN")).transact({"from": a})
    tw.functions.setName(b32("SOPHIE")).transact({"from": a})
    assert lisible(tw.functions.names(a).call()) == "SOPHIE"


def test_pseudo_accentue_et_long(tw, accounts):
    """31 octets utiles : un pseudo raisonnable passe, meme accentue."""
    a = accounts[1]
    tw.functions.setName(b32("ZOE-31")).transact({"from": a})
    assert lisible(tw.functions.names(a).call()) == "ZOE-31"


def test_pseudos_en_une_lecture(tw, accounts):
    """Le classement lit tous les pseudos d'un coup : un appel par joueur
    saturerait le RPC public pendant la demo."""
    a, b, c = accounts[1], accounts[2], accounts[3]
    tw.functions.setName(b32("ALICE")).transact({"from": a})
    tw.functions.setName(b32("BOB")).transact({"from": b})
    # c n'a pas de pseudo

    noms = tw.functions.namesOf([a, b, c]).call()
    assert [lisible(n) for n in noms] == ["ALICE", "BOB", ""]


def test_evenement_named(w3, tw, accounts):
    rcpt = w3.eth.wait_for_transaction_receipt(
        tw.functions.setName(b32("KEVIN")).transact({"from": accounts[1]}))
    ev = tw.events.Named().process_receipt(rcpt)[0]["args"]
    assert ev["player"] == accounts[1] and lisible(ev["name"]) == "KEVIN"


def test_destination_par_defaut(tw, accounts):
    """Sans declaration, on paie le wallet de jeu lui-meme."""
    a = accounts[1]
    assert tw.functions.payoutTo(a).call() == ZERO
    assert tw.functions.destinationOf(a).call() == a


def test_destination_declaree(tw, accounts):
    jeu, vrai = accounts[1], accounts[5]
    tw.functions.setPayout(vrai).transact({"from": jeu})
    assert tw.functions.destinationOf(jeu).call() == vrai


def test_les_gains_suivent_la_destination(w3, tw, accounts, admin):
    """
    Le scenario reel : on joue avec le wallet jetable du navigateur, et on
    encaisse sur son vrai wallet.
    """
    jeu, vrai = accounts[1], accounts[6]
    tw.functions.claim(0, 1).transact({"from": jeu})
    tw.functions.setPayout(vrai).transact({"from": jeu})
    w3.eth.send_transaction({"from": accounts[8], "to": tw.address,
                             "value": Web3.to_wei(4, "ether")})

    avant_jeu = w3.eth.get_balance(jeu)
    avant_vrai = w3.eth.get_balance(vrai)
    tw.functions.endRound([jeu], [1]).transact({"from": admin})

    assert w3.eth.get_balance(vrai) - avant_vrai == Web3.to_wei(4, "ether")
    assert w3.eth.get_balance(jeu) == avant_jeu          # le wallet de jeu ne bouge pas


def test_repli_credite_le_wallet_de_jeu(w3, tw, accounts, admin, rejecter):
    """
    Si la destination declaree refuse les fonds, le repli doit creder
    l'adresse de jeu : c'est la seule que le joueur controle a coup sur.
    """
    jeu = accounts[1]
    tw.functions.setPayout(rejecter.address).transact({"from": jeu})
    w3.eth.send_transaction({"from": accounts[8], "to": tw.address,
                             "value": Web3.to_wei(2, "ether")})

    tw.functions.endRound([jeu], [1]).transact({"from": admin})

    assert tw.functions.rewards(jeu).call() == Web3.to_wei(2, "ether")
    assert tw.functions.rewards(rejecter.address).call() == 0


def test_le_pseudo_nest_pas_requis_pour_jouer(tw, accounts):
    """Zero friction : on peint sans jamais avoir declare quoi que ce soit."""
    a = accounts[1]
    tw.functions.claim(5, 3).transact({"from": a})
    assert tw.functions.claimsOf(a).call() == 1
    assert tw.functions.names(a).call() == b"\x00" * 32
