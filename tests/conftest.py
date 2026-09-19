"""
Banc de test e2e : un EVM complet en memoire, aucune connexion reseau.

On teste le contrat reellement deploye et execute, pas une simulation : les
couts de gas mesures ici sont ceux de l'EVM, donc directement exploitables
pour calibrer les constantes du front.
"""
import os
import pytest
import solcx
from web3 import Web3, EthereumTesterProvider

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "contracts", "SplashWar.sol")
SOLC = "0.8.24"

# Contrat qui refuse tout paiement : sert a verifier le repli de endRound.
REJECTER = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
contract Rejecter {
    receive() external payable { revert("non"); }
}
"""


def _compile():
    if SOLC not in [str(v) for v in solcx.get_installed_solc_versions()]:
        solcx.install_solc(SOLC)
    main = solcx.compile_files([SOURCE], output_values=["abi", "bin"],
                               solc_version=SOLC, optimize=True, optimize_runs=200,
                               evm_version="shanghai")
    key = next(k for k in main if k.endswith(":SplashWar"))
    rej = solcx.compile_source(REJECTER, output_values=["abi", "bin"],
                               solc_version=SOLC, evm_version="shanghai")
    rkey = next(k for k in rej if k.endswith(":Rejecter"))
    return main[key], rej[rkey]


ART, REJ_ART = _compile()


@pytest.fixture
def w3():
    return Web3(EthereumTesterProvider())


@pytest.fixture
def accounts(w3):
    return w3.eth.accounts


@pytest.fixture
def admin(accounts):
    return accounts[0]


@pytest.fixture
def tw(w3, admin):
    """SplashWar fraichement deploye, admin = accounts[0]."""
    c = w3.eth.contract(abi=ART["abi"], bytecode=ART["bin"])
    tx = c.constructor().transact({"from": admin})
    rcpt = w3.eth.wait_for_transaction_receipt(tx)
    return w3.eth.contract(address=rcpt.contractAddress, abi=ART["abi"])


@pytest.fixture
def rejecter(w3, admin):
    c = w3.eth.contract(abi=REJ_ART["abi"], bytecode=REJ_ART["bin"])
    tx = c.constructor().transact({"from": admin})
    rcpt = w3.eth.wait_for_transaction_receipt(tx)
    return w3.eth.contract(address=rcpt.contractAddress, abi=REJ_ART["abi"])


def gas_of(w3, tx_hash):
    return w3.eth.wait_for_transaction_receipt(tx_hash).gasUsed


# ---------------------------------------------------------------------------
# Verification des erreurs custom
#
# Les erreurs custom coutent moins de gas qu'un require avec message, mais
# elles remontent comme 4 octets bruts. On verifie le selecteur exact plutot
# que "ca a revert", sinon un test passe pour la mauvaise raison.
# ---------------------------------------------------------------------------

ERRORS = {
    "BadCell":      "608eeee9",
    "BadColor":     "45f1af89",
    "Cooldown":     "b0782df7",
    "AlreadyYours": "3e817dc8",
    "NotAdmin":     "7bfa4b9f",
    "BadInput":     "2bb9acf7",
    "Empty":        "3db2a12a",
}


def _selector_of(exc):
    """
    Extrait le selecteur d'erreur d'une exception de revert.
    Selon la couche qui leve, les 4 octets arrivent soit en bytes, soit en
    hexa, soit dans la repr d'un bytes glissee dans un message texte.
    """
    import ast
    import re

    for arg in getattr(exc, "args", ()):
        if isinstance(arg, (bytes, bytearray)):
            return bytes(arg)[:4].hex()
        texte = str(arg)
        trouve = re.search(r"b(['\"])(.*?)\1", texte, re.S)
        if trouve:
            try:
                return ast.literal_eval("b" + trouve.group(1) + trouve.group(2)
                                        + trouve.group(1))[:4].hex()
            except Exception:
                pass
        trouve = re.search(r"0x([0-9a-fA-F]{8})", texte)
        if trouve:
            return trouve.group(1).lower()
    return ""


def expect_revert(nom, fn, tx):
    """Execute fn.transact(tx) et exige le revert custom `nom`, pas un autre."""
    from eth_tester.exceptions import TransactionFailed
    from web3.exceptions import ContractLogicError

    attendu = ERRORS[nom]
    try:
        fn.transact(tx)
    except (TransactionFailed, ContractLogicError) as exc:
        obtenu = _selector_of(exc)
        assert obtenu == attendu, (
            f"revert attendu {nom} ({attendu}), obtenu {obtenu or '?'} : {str(exc)[:110]}")
        return
    raise AssertionError(f"aucun revert alors que {nom} etait attendu")
