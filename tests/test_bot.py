"""
bot.py de bout en bout contre un EVM reel.

On exerce le vrai code : generation de wallets, financement multi-sources avec
nonces suivis localement, envoi de transactions signees hors ligne, relecture
des logs pour identifier les joueurs. Rien n'est simule.
"""
import json
import os
import sys

import pytest
from web3 import Web3, EthereumTesterProvider

# Le chain id doit etre pose avant l'import : bot.py le lit au chargement.
os.environ["MONAD_CHAIN_ID"] = str(Web3(EthereumTesterProvider()).eth.chain_id)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot  # noqa: E402


@pytest.fixture
def wallets_file(tmp_path, monkeypatch):
    chemin = tmp_path / "wallets.json"
    monkeypatch.setattr(bot, "WALLETS_FILE", str(chemin))
    return chemin


@pytest.fixture
def funder(w3, accounts):
    """Compte source dont on possede la cle, alimente depuis un compte de test."""
    compte = bot.Account.create()
    w3.eth.send_transaction({"from": accounts[0], "to": compte.address,
                             "value": Web3.to_wei(50, "ether")})
    return compte


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_generation_de_wallets(wallets_file):
    bot.cmd_gen(Args(n=5, replace=True))
    data = json.loads(wallets_file.read_text())
    assert len(data["wallets"]) == 5
    assert all(w["address"].startswith("0x") for w in data["wallets"])
    assert len({w["address"] for w in data["wallets"]}) == 5      # pas de doublon
    assert oct(wallets_file.stat().st_mode)[-3:] == "600"         # fichier de cles

    # relance sans --replace : on complete, on n'ecrase pas
    bot.cmd_gen(Args(n=8, replace=False))
    apres = json.loads(wallets_file.read_text())["wallets"]
    assert len(apres) == 8
    assert apres[:5] == data["wallets"]


def test_financement_multi_sources(w3, accounts, wallets_file, monkeypatch):
    """Deux sources, six cibles : la repartition doit couvrir tout le monde."""
    monkeypatch.setattr(bot, "BLOCKS_BEFORE_SPEND", 0)
    sources = []
    for montant in (1, 2):
        c = bot.Account.create()
        w3.eth.send_transaction({"from": accounts[0], "to": c.address,
                                 "value": Web3.to_wei(montant, "ether")})
        sources.append(c)

    bot.cmd_gen(Args(n=6, replace=True))
    cibles = [w["address"] for w in json.loads(wallets_file.read_text())["wallets"]]
    balances = {s.address: w3.eth.get_balance(s.address) for s in sources}
    sources.sort(key=lambda s: balances[s.address], reverse=True)

    envoyes = bot.send_funds(w3, sources, balances, cibles,
                             Web3.to_wei(0.3, "ether"), delay=0)

    assert envoyes == 6
    for addr in cibles:
        assert w3.eth.get_balance(addr) == Web3.to_wei(0.3, "ether")


def test_reserve_insuffisante_echoue_proprement(w3, accounts, wallets_file):
    """Mieux vaut sortir avec un message qu'assecher la source a mi-chemin."""
    source = bot.Account.create()
    w3.eth.send_transaction({"from": accounts[0], "to": source.address,
                             "value": Web3.to_wei(0.5, "ether")})
    balances = {source.address: w3.eth.get_balance(source.address)}
    cibles = [bot.Account.create().address for _ in range(10)]

    with pytest.raises(SystemExit) as sortie:
        bot.send_funds(w3, [source], balances, cibles,
                       Web3.to_wei(1, "ether"), delay=0)
    assert "insuffisante" in str(sortie.value)


def test_envoi_de_poses_reelles(w3, tw, accounts, funder):
    """
    Le coeur du bot : signer hors ligne, suivre son nonce, envoyer en rafale.
    On verifie que les cases sont bien peintes onchain.
    """
    joueur = bot.Account.create()
    w3.eth.send_transaction({"from": accounts[0], "to": joueur.address,
                             "value": Web3.to_wei(1, "ether")})

    sender = bot.Sender(w3, joueur.key.hex(), tw.address)
    max_fee, tip = bot.fees(w3)

    poses = [(10, 4), (11, 4), (12, 9), (300, 16)]
    for cell, color in poses:
        assert sender.fire(cell, color, max_fee, tip) is None

    assert sender.sent == 4 and sender.failed == 0
    board = tw.functions.getColors().call()
    for cell, color in poses:
        assert board[cell] == color
    assert tw.functions.claimsOf(joueur.address).call() == 4
    assert tw.functions.ownerOf(10).call() == joueur.address


def test_le_nonce_se_recale_apres_un_echec(w3, tw, accounts):
    """Un wallet vide doit echouer sans laisser le nonce dans le decor."""
    pauvre = bot.Account.create()
    sender = bot.Sender(w3, pauvre.key.hex(), tw.address)
    max_fee, tip = bot.fees(w3)

    assert sender.fire(5, 1, max_fee, tip) is not None      # message d'erreur
    assert sender.failed == 1
    assert sender.dead is True
    assert sender.nonce == w3.eth.get_transaction_count(pauvre.address, "pending")


def test_scan_des_joueurs_dans_les_logs(w3, tw, accounts, funder):
    """
    refill repose la-dessus : identifier les joueurs sans leur demander leur
    adresse, en relisant leurs propres transactions.
    """
    depart = w3.eth.block_number
    joueurs = []
    for i in range(3):
        c = bot.Account.create()
        w3.eth.send_transaction({"from": accounts[0], "to": c.address,
                                 "value": Web3.to_wei(1, "ether")})
        joueurs.append(c)

    max_fee, tip = bot.fees(w3)
    attendu = {}
    for i, c in enumerate(joueurs):
        sender = bot.Sender(w3, c.key.hex(), tw.address)
        for j in range(i + 1):                      # 1, 2 puis 3 poses
            sender.fire(i * 50 + j, (i % 16) + 1, max_fee, tip)
        attendu[c.address] = i + 1

    trouves = bot.scan_players(w3, tw.address, since=depart)
    assert trouves == attendu


def test_claim_data_encode_correctement(tw):
    """L'encodage manuel doit correspondre a l'ABI, sinon tout part en revert."""
    data = bot.claim_data(777, 13)
    attendu = tw.encode_abi("claim", args=[777, 13])
    assert "0x" + data.hex() == attendu


# ---------------------------------------------------------------------------
# Classement et distribution de la cagnotte
# ---------------------------------------------------------------------------

@pytest.fixture
def tw_admin(w3, accounts):
    """
    SplashWar deploye par un compte dont on possede la cle, pour pouvoir
    exercer les fonctions d'administration comme le ferait bot.py payout.
    """
    from conftest import ART
    admin = bot.Account.create()
    w3.eth.send_transaction({"from": accounts[0], "to": admin.address,
                             "value": Web3.to_wei(10, "ether")})
    c = w3.eth.contract(abi=ART["abi"], bytecode=ART["bin"])
    tx = c.constructor().build_transaction({
        "from": admin.address, "nonce": 0, "chainId": bot.CHAIN_ID,
        "gas": 3_000_000, "gasPrice": w3.eth.gas_price,
    })
    h = w3.eth.send_raw_transaction(bot.raw_of(admin.sign_transaction(tx)))
    addr = w3.eth.wait_for_transaction_receipt(h).contractAddress
    return admin, w3.eth.contract(address=addr, abi=ART["abi"])


_cles_utilisees = []


def _peindre(w3, accounts, contrat, repartition):
    """Fait poser des cases par des joueurs jetables. repartition = [n1, n2, ...]"""
    joueurs, cell = [], 0
    _cles_utilisees.clear()
    max_fee, tip = bot.fees(w3)
    for n in repartition:
        c = bot.Account.create()
        w3.eth.send_transaction({"from": accounts[0], "to": c.address,
                                 "value": Web3.to_wei(1, "ether")})
        sender = bot.Sender(w3, c.key.hex(), contrat.address)
        for _ in range(n):
            sender.fire(cell, 4, max_fee, tip)
            cell += 1
        joueurs.append(c.address)
        _cles_utilisees.append(c)
    return joueurs


def test_classement_par_territoire(w3, tw, accounts, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)          # pas de deployment.json parasite
    joueurs = _peindre(w3, accounts, tw, [5, 3, 1])
    c = bot.contract_of(w3, tw.address)

    classement = bot.leaderboard(w3, c)
    assert [a for a, _, _, _ in classement] == joueurs
    assert [n for _, n, _, _ in classement] == [5, 3, 1]
    assert [p for _, _, p, _ in classement] == [5, 3, 1]  # poses = tenu, personne recouvert
    assert [x for _, _, _, x in classement] == ["", "", ""]  # aucun pseudo declare


def test_le_classement_recompense_ce_qu_on_tient_pas_ce_qu_on_a_pose(
        w3, tw, accounts, monkeypatch, tmp_path):
    """
    Le joueur qui pose beaucoup mais se fait recouvrir doit tomber au classement.
    C'est toute la tension du jeu.
    """
    monkeypatch.chdir(tmp_path)
    max_fee, tip = bot.fees(w3)
    bosseur, sniper = [], []
    for cible in (bosseur, sniper):
        c = bot.Account.create()
        w3.eth.send_transaction({"from": accounts[0], "to": c.address,
                                 "value": Web3.to_wei(1, "ether")})
        cible.append(c)
    bosseur, sniper = bosseur[0], sniper[0]

    sb = bot.Sender(w3, bosseur.key.hex(), tw.address)
    for cell in range(10):
        sb.fire(cell, 4, max_fee, tip)

    ss = bot.Sender(w3, sniper.key.hex(), tw.address)
    for cell in range(8):                       # recouvre 8 des 10 cases
        ss.fire(cell, 9, max_fee, tip)

    classement = bot.leaderboard(w3, bot.contract_of(w3, tw.address))
    par_adresse = {a: (tenu, poses) for a, tenu, poses, _ in classement}
    assert par_adresse[bosseur.address] == (2, 10)   # a beaucoup pose, tient peu
    assert par_adresse[sniper.address] == (8, 8)
    assert classement[0][0] == sniper.address        # le sniper mene


def test_payout_distribue_et_cloture(w3, accounts, tw_admin, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    admin, contrat = tw_admin
    monkeypatch.setattr(bot, "connect", lambda rpc: w3)

    joueurs = _peindre(w3, accounts, contrat, [6, 4, 2])
    w3.eth.send_transaction({"from": accounts[0], "to": contrat.address,
                             "value": Web3.to_wei(10, "ether")})
    avant = {a: w3.eth.get_balance(a) for a in joueurs}

    bot.cmd_payout(Args(rpc="local", contract=contrat.address, key=admin.key.hex(),
                        shares="5,3,2", dry_run=False))

    assert w3.eth.get_balance(joueurs[0]) - avant[joueurs[0]] == Web3.to_wei(5, "ether")
    assert w3.eth.get_balance(joueurs[1]) - avant[joueurs[1]] == Web3.to_wei(3, "ether")
    assert w3.eth.get_balance(joueurs[2]) - avant[joueurs[2]] == Web3.to_wei(2, "ether")
    assert contrat.functions.epoch().call() == 2                      # manche clôturee
    assert sum(1 for x in contrat.functions.getColors().call() if x) == 0


def test_payout_dry_run_ne_touche_a_rien(w3, accounts, tw_admin, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    admin, contrat = tw_admin
    monkeypatch.setattr(bot, "connect", lambda rpc: w3)
    _peindre(w3, accounts, contrat, [3, 1])
    w3.eth.send_transaction({"from": accounts[0], "to": contrat.address,
                             "value": Web3.to_wei(4, "ether")})

    bot.cmd_payout(Args(rpc="local", contract=contrat.address, key=admin.key.hex(),
                        shares="5,3,2", dry_run=True))

    assert contrat.functions.prizePool().call() == Web3.to_wei(4, "ether")
    assert contrat.functions.epoch().call() == 1


def test_le_classement_remonte_les_pseudos(w3, tw, accounts, monkeypatch, tmp_path):
    """
    Le classement doit etre lisible au videoprojecteur : c'est toute la raison
    d'etre du pseudo. Il est lu en une seule requete pour tous les joueurs.
    """
    monkeypatch.chdir(tmp_path)
    joueurs = _peindre(w3, accounts, tw, [4, 2])
    max_fee, tip = bot.fees(w3)

    # le premier se nomme, le second non
    c_ecriture = w3.eth.contract(address=tw.address, abi=tw.abi)
    donnees = c_ecriture.encode_abi("setName", args=[b"ALICE".ljust(32, b"\x00")])
    cle = [k for k in _cles_utilisees if k.address == joueurs[0]][0]
    tx = {"to": tw.address, "data": donnees, "gas": 80000, "value": 0,
          "maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip, "type": 2,
          "chainId": bot.CHAIN_ID,
          "nonce": w3.eth.get_transaction_count(cle.address, "pending")}
    w3.eth.send_raw_transaction(bot.raw_of(cle.sign_transaction(tx)))

    classement = bot.leaderboard(w3, bot.contract_of(w3, tw.address))
    pseudos = {a: p for a, _, _, p in classement}
    assert pseudos[joueurs[0]] == "ALICE"
    assert pseudos[joueurs[1]] == ""
