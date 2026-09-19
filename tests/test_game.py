"""Regles du jeu : pose, ecrasement, palette, manches, cooldown, administration."""
import pytest
from web3.exceptions import ContractLogicError
from conftest import gas_of, expect_revert


def test_constantes(tw, admin):
    assert tw.functions.WIDTH().call() == 32
    assert tw.functions.HEIGHT().call() == 32
    assert tw.functions.CELLS().call() == 1024
    assert tw.functions.COLORS().call() == 16
    assert tw.functions.epoch().call() == 1
    assert tw.functions.cooldownBlocks().call() == 0   # debit maximum par defaut
    assert tw.functions.admin().call() == admin


def test_pose_simple(w3, tw, accounts):
    a = accounts[1]
    tw.functions.claim(42, 4).transact({"from": a})
    assert tw.functions.getColors().call()[42] == 4
    assert tw.functions.ownerOf(42).call() == a
    assert tw.functions.claimsOf(a).call() == 1
    assert tw.functions.getOwners().call()[42] == a


def test_toute_la_palette(w3, tw, accounts):
    """Les 16 indices sont acceptes, 0 et 17 sont refuses."""
    for color in range(1, 17):
        tw.functions.claim(color, color).transact({"from": accounts[1]})
    board = tw.functions.getColors().call()
    for color in range(1, 17):
        assert board[color] == color

    for mauvais in (0, 17, 255):
        expect_revert("BadColor", tw.functions.claim(500, mauvais), {"from": accounts[1]})


def test_case_hors_grille(tw, accounts):
    expect_revert("BadCell", tw.functions.claim(1024, 1), {"from": accounts[1]})
    tw.functions.claim(1023, 1).transact({"from": accounts[1]})   # derniere case valide


def test_repeindre_sa_case_meme_couleur_refuse(tw, accounts):
    """Evite de bruler du gas quand le doigt s'attarde sur une case."""
    a = accounts[1]
    tw.functions.claim(10, 3).transact({"from": a})
    expect_revert("AlreadyYours", tw.functions.claim(10, 3), {"from": a})


def test_changer_la_couleur_de_sa_propre_case_autorise(tw, accounts):
    """Le joueur doit pouvoir corriger sa teinte sans perdre la case."""
    a = accounts[1]
    tw.functions.claim(10, 3).transact({"from": a})
    tw.functions.claim(10, 9).transact({"from": a})
    assert tw.functions.getColors().call()[10] == 9
    assert tw.functions.claimsOf(a).call() == 2


def test_ecrasement_par_un_autre_joueur(tw, accounts):
    a, b = accounts[1], accounts[2]
    tw.functions.claim(7, 1).transact({"from": a})
    tw.functions.claim(7, 9).transact({"from": b})
    assert tw.functions.ownerOf(7).call() == b
    assert tw.functions.getColors().call()[7] == 9
    assert tw.functions.claimsOf(a).call() == 1      # le compteur d'effort reste acquis


def test_scores_par_couleur(tw, accounts):
    for cell in range(5):
        tw.functions.claim(cell, 4).transact({"from": accounts[1]})
    for cell in range(5, 8):
        tw.functions.claim(cell, 9).transact({"from": accounts[2]})
    scores = tw.functions.colorScores().call()
    assert scores[4] == 5
    assert scores[9] == 3
    assert sum(scores) == 8
    assert scores[0] == 0                            # index 0 inutilise


def test_territoire_par_joueur(tw, accounts):
    a, b = accounts[1], accounts[2]
    for cell in range(6):
        tw.functions.claim(cell, 1).transact({"from": a})
    for cell in (0, 1):                              # b reprend deux cases a a
        tw.functions.claim(cell, 9).transact({"from": b})
    owners = tw.functions.getOwners().call()
    assert owners.count(a) == 4
    assert owners.count(b) == 2


def test_reset_invalide_le_plateau(tw, accounts, admin):
    a = accounts[1]
    for cell in range(20):
        tw.functions.claim(cell, 2).transact({"from": a})
    assert sum(1 for c in tw.functions.getColors().call() if c) == 20

    tw.functions.reset().transact({"from": admin})

    assert tw.functions.epoch().call() == 2
    assert sum(1 for c in tw.functions.getColors().call() if c) == 0
    assert all(o == "0x" + "00" * 20 for o in tw.functions.getOwners().call())
    assert tw.functions.ownerOf(0).call() == "0x" + "00" * 20
    # l'effort cumule survit a la manche, c'est la memoire du joueur
    assert tw.functions.claimsOf(a).call() == 20


def test_reset_cout_constant(w3, tw, accounts, admin):
    """Vider 1024 cases doit couter le meme prix que vider un plateau vide."""
    vide = gas_of(w3, tw.functions.reset().transact({"from": admin}))
    for cell in range(200):
        tw.functions.claim(cell, 5).transact({"from": accounts[1]})
    plein = gas_of(w3, tw.functions.reset().transact({"from": admin}))
    assert abs(plein - vide) < 200, (vide, plein)


def test_cooldown(w3, tw, accounts, admin):
    a = accounts[1]
    tw.functions.setCooldown(5).transact({"from": admin})
    tw.functions.claim(1, 1).transact({"from": a})
    expect_revert("Cooldown", tw.functions.claim(2, 1), {"from": a})
    # un autre joueur n'est pas gene : le cooldown est par adresse
    tw.functions.claim(3, 1).transact({"from": accounts[2]})

    tw.functions.setCooldown(0).transact({"from": admin})
    tw.functions.claim(4, 1).transact({"from": a})    # de nouveau libre


def test_administration_protegee(tw, accounts):
    intrus = accounts[3]
    for appel in (tw.functions.reset(), tw.functions.setCooldown(3),
                  tw.functions.setAdmin(intrus)):
        expect_revert("NotAdmin", appel, {"from": intrus})


def test_transfert_admin(tw, accounts, admin):
    nouveau = accounts[4]
    tw.functions.setAdmin(nouveau).transact({"from": admin})
    assert tw.functions.admin().call() == nouveau
    tw.functions.reset().transact({"from": nouveau})
    expect_revert("NotAdmin", tw.functions.reset(), {"from": admin})


def test_evenement_claimed(w3, tw, accounts):
    a = accounts[1]
    rcpt = w3.eth.wait_for_transaction_receipt(
        tw.functions.claim(123, 7).transact({"from": a}))
    ev = tw.events.Claimed().process_receipt(rcpt)[0]["args"]
    assert (ev["epoch"], ev["cell"], ev["player"], ev["color"]) == (1, 123, a, 7)
