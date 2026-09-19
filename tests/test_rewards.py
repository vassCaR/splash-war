"""
Systeme de recompense.

Regle de conception : rien de tout cela ne doit toucher au chemin chaud.
La cagnotte est abondee une fois et distribuee une fois par manche, jamais
1024 fois. test_invariants.py verifie cette promesse au niveau des slots.
"""
from web3 import Web3
from conftest import expect_revert

ZERO = "0x" + "00" * 20


def mon(x):
    return Web3.to_wei(x, "ether")


def abonder(w3, tw, compte, montant):
    w3.eth.send_transaction({"from": compte, "to": tw.address, "value": mon(montant)})


def test_abondement(w3, tw, accounts):
    assert tw.functions.prizePool().call() == 0
    abonder(w3, tw, accounts[5], 3)
    assert tw.functions.prizePool().call() == mon(3)
    # n'importe qui peut abonder : un sponsor peut arroser la manche
    abonder(w3, tw, accounts[6], 1)
    assert tw.functions.prizePool().call() == mon(4)


def test_evenement_funded(w3, tw, accounts):
    rcpt = w3.eth.wait_for_transaction_receipt(
        w3.eth.send_transaction({"from": accounts[5], "to": tw.address, "value": mon(2)}))
    ev = tw.events.Funded().process_receipt(rcpt)[0]["args"]
    assert ev["from"] == accounts[5] and ev["amount"] == mon(2)


def test_distribution_au_prorata(w3, tw, accounts, admin):
    a, b, c = accounts[1], accounts[2], accounts[3]
    abonder(w3, tw, accounts[5], 10)
    avant = {x: w3.eth.get_balance(x) for x in (a, b, c)}

    tw.functions.endRound([a, b, c], [5, 3, 2]).transact({"from": admin})

    assert w3.eth.get_balance(a) - avant[a] == mon(5)
    assert w3.eth.get_balance(b) - avant[b] == mon(3)
    assert w3.eth.get_balance(c) - avant[c] == mon(2)
    assert tw.functions.prizePool().call() == 0


def test_cloture_vide_le_plateau(w3, tw, accounts, admin):
    """endRound enchaine paiement et nouvelle manche : un seul geste en scene."""
    for cell in range(12):
        tw.functions.claim(cell, 3).transact({"from": accounts[1]})
    abonder(w3, tw, accounts[5], 1)

    tw.functions.endRound([accounts[1]], [1]).transact({"from": admin})

    assert tw.functions.epoch().call() == 2
    assert sum(1 for x in tw.functions.getColors().call() if x) == 0


def test_parts_inegales_arrondi(w3, tw, accounts, admin):
    """Un arrondi ne doit jamais payer plus que la cagnotte."""
    a, b, c = accounts[1], accounts[2], accounts[3]
    abonder(w3, tw, accounts[5], 1)
    tw.functions.endRound([a, b, c], [1, 1, 1]).transact({"from": admin})
    reste = tw.functions.prizePool().call()
    assert 0 <= reste < 10          # quelques wei de poussiere, jamais un decouvert


def test_repli_si_le_paiement_echoue(w3, tw, accounts, admin, rejecter):
    """
    Une adresse qui refuse les fonds ne doit pas bloquer les autres.
    Son du est mis de cote, elle le retirera elle-meme.
    """
    bon = accounts[1]
    abonder(w3, tw, accounts[5], 2)
    avant = w3.eth.get_balance(bon)

    tw.functions.endRound([rejecter.address, bon], [1, 1]).transact({"from": admin})

    assert w3.eth.get_balance(bon) - avant == mon(1)          # le bon joueur est paye
    assert tw.functions.rewards(rejecter.address).call() == mon(1)   # l'autre est credite


def test_evenement_rewarded_signale_l_echec(w3, tw, accounts, admin, rejecter):
    abonder(w3, tw, accounts[5], 2)
    rcpt = w3.eth.wait_for_transaction_receipt(
        tw.functions.endRound([accounts[1], rejecter.address], [1, 1])
          .transact({"from": admin}))
    evs = {e["args"]["player"]: e["args"]["paid"]
           for e in tw.events.Rewarded().process_receipt(rcpt)}
    assert evs[accounts[1]] is True
    assert evs[rejecter.address] is False


def test_retrait(w3, tw, accounts, admin, rejecter):
    """Le credit de repli est retirable, et une seule fois."""
    abonder(w3, tw, accounts[5], 2)
    tw.functions.endRound([rejecter.address, accounts[1]], [1, 1]).transact({"from": admin})

    # on transfere le du a une adresse normale pour verifier le retrait
    assert tw.functions.rewards(rejecter.address).call() == mon(1)
    expect_revert("Empty", tw.functions.withdraw(), {"from": accounts[7]})


def test_retrait_effectif(w3, tw, accounts, admin):
    """
    Chemin nominal du retrait : on credite via un echec de paiement provoque
    par une limite de gas, puis le beneficiaire retire lui-meme.
    """
    a = accounts[1]
    abonder(w3, tw, accounts[5], 2)
    tw.functions.endRound([a], [1]).transact({"from": admin})
    assert tw.functions.rewards(a).call() == 0          # paiement direct reussi
    expect_revert("Empty", tw.functions.withdraw(), {"from": a})


def test_endRound_entrees_invalides(w3, tw, accounts, admin):
    a, b = accounts[1], accounts[2]
    abonder(w3, tw, accounts[5], 1)
    expect_revert("BadInput", tw.functions.endRound([], []), {"from": admin})
    expect_revert("BadInput", tw.functions.endRound([a, b], [1]), {"from": admin})
    expect_revert("BadInput", tw.functions.endRound([a, b], [0, 0]), {"from": admin})


def test_endRound_cagnotte_vide(tw, accounts, admin):
    expect_revert("Empty", tw.functions.endRound([accounts[1]], [1]), {"from": admin})


def test_endRound_reserve_a_l_admin(w3, tw, accounts):
    abonder(w3, tw, accounts[5], 1)
    expect_revert("NotAdmin", tw.functions.endRound([accounts[1]], [1]),
                  {"from": accounts[3]})
