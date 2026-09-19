"""
Test de bout en bout du front, dans un vrai navigateur, contre une vraie chaine.

Ce test n'est pas dans la suite pytest : il demande anvil et un serveur
statique en marche. Il se lance a la main.

    anvil --host 127.0.0.1 --port 8545 --chain-id 31337 --block-time 1 &
    (cd web && python3 -m http.server 8080 &)
    MONAD_RPC=http://127.0.0.1:8545 MONAD_CHAIN_ID=31337 \
      .venv/bin/python scripts/deploy.py --no-write-front --key <cle_anvil_0>
    .venv/bin/python tests/e2e_front.py     # adapter CONTRAT ci-dessous

Il a deja rattrape un bug que rien d'autre ne pouvait voir : le front
calculait sa limite de gas APRES la peinture optimiste, croyait donc toujours
viser une case deja peinte, envoyait une limite trop basse, et les 25
transactions du glisse mouraient en OutOfGas. Payees, et perdues. Aucun test
unitaire ne pouvait l'attraper : le contrat etait juste, la formule de gas
etait juste, seul le cablage entre les deux etait faux.

On seme une cle connue dans localStorage, on la finance depuis anvil, on
glisse sur le plateau, puis on verifie cote chaine que les poses ont abouti.
"""
import sys, time
sys.path.insert(0, "/home/jean/dev/monad_blitz")
import os
os.environ["MONAD_CHAIN_ID"] = "31337"
from web3 import Web3
from eth_account import Account
from playwright.sync_api import sync_playwright

RPC = "http://127.0.0.1:8545"
C = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
ANVIL0 = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

w3 = Web3(Web3.HTTPProvider(RPC))
joueur = Account.create()
src = Account.from_key(ANVIL0)
tx = {"to": joueur.address, "value": Web3.to_wei(5, "ether"), "gas": 21000,
      "gasPrice": w3.eth.gas_price, "nonce": w3.eth.get_transaction_count(src.address),
      "chainId": 31337}
h = w3.eth.send_raw_transaction(src.sign_transaction(tx).raw_transaction)
w3.eth.wait_for_transaction_receipt(h)
print(f"joueur {joueur.address} finance : {Web3.from_wei(w3.eth.get_balance(joueur.address),'ether')} MON")

abi = [{"name":"claimsOf","type":"function","stateMutability":"view",
        "inputs":[{"name":"p","type":"address"}],"outputs":[{"type":"uint32"}]}]
c = w3.eth.contract(address=Web3.to_checksum_address(C), abi=abi)

URL = f"http://127.0.0.1:8080/?contract={C}&rpc={RPC}&chainid=31337"
S = "/tmp/claude-1000/-home-jean-dev-monad-blitz/cc002d3c-5e76-41e8-a0e4-efa01c1ee78f/scratchpad"

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1600, "height": 1000})
    erreurs = []
    pg.on("pageerror", lambda e: erreurs.append(str(e)))
    pg.on("console", lambda m: erreurs.append(m.text) if m.type == "error" else None)
    # cle semee avant tout script de la page
    pg.add_init_script(f"localStorage.setItem('tw.pk', '{joueur.key.hex()}');"
                       f"localStorage.setItem('tw.color', '11');")
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(3000)

    etat = pg.evaluate("() => ({credit: credit.textContent, solde: wBal.textContent.trim(),"
                       " attract: attract.classList.contains('on')})")
    print("avant le glisse :", etat)
    pg.screenshot(path=f"{S}/jeu-credite.png")

    # glisse en diagonale sur le plateau
    box = pg.locator("#board").bounding_box()
    pg.mouse.move(box["x"] + 30, box["y"] + 30)
    pg.mouse.down()
    for i in range(1, 26):
        pg.mouse.move(box["x"] + 30 + i * 22, box["y"] + 30 + i * 22)
        pg.wait_for_timeout(45)
    pg.mouse.up()
    pg.wait_for_timeout(5000)

    apres = pg.evaluate("() => ({envoyees: wSent.textContent, echecs: wErr.textContent,"
                        " credit: credit.textContent, tps: document.querySelector('#tps .v').textContent})")
    print("apres le glisse :", apres)
    print("onchain claimsOf :", c.functions.claimsOf(joueur.address).call())
    pg.screenshot(path=f"{S}/jeu-apres-glisse.png")
    if erreurs: print("ERREURS CONSOLE :", erreurs[:5])
    else: print("aucune erreur console")
    b.close()
