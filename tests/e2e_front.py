"""
Parcours complet du MVP, dans un vrai navigateur, contre une vraie chaine.

Ce test n'est pas dans la suite pytest : il demande anvil et un serveur
statique en marche. Il se lance a la main.

    anvil --host 127.0.0.1 --port 8545 --chain-id 31337 --block-time 1 &
    (cd web && python3 -m http.server 8080 &)
    MONAD_RPC=http://127.0.0.1:8545 MONAD_CHAIN_ID=31337 \
      .venv/bin/python scripts/deploy.py --no-write-front --key <cle_anvil_0>
    .venv/bin/python tests/e2e_front.py 0xAdresseDuContrat

Il a deja rattrape un bug que rien d'autre ne pouvait voir : le front
calculait sa limite de gas APRES la peinture optimiste, croyait donc toujours
viser une case deja peinte, envoyait une limite trop basse, et les poses d'un
glisse mouraient en OutOfGas. Payees, et perdues. Aucun test unitaire ne
pouvait l'attraper : le contrat etait juste, la formule de gas etait juste,
seul le cablage entre les deux etait faux.

Etapes couvertes : wallet jetable finance, pseudo onchain, glisse au doigt,
destination de gains declaree, cagnotte abondee, cloture et paiement.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MONAD_CHAIN_ID", "31337")

from web3 import Web3
from eth_account import Account
from playwright.sync_api import sync_playwright

import bot

RPC = os.environ.get("MONAD_RPC", "http://127.0.0.1:8545")
CHAIN = int(os.environ.get("MONAD_CHAIN_ID", "31337"))
ANVIL0 = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
S = "/tmp/claude-1000/-home-jean-dev-monad-blitz/cc002d3c-5e76-41e8-a0e4-efa01c1ee78f/scratchpad"

CONTRAT = sys.argv[1] if len(sys.argv) > 1 else json.load(open('deployment.json'))['address']
ABI = json.load(open("deployment.json"))["abi"]

w3 = Web3(Web3.HTTPProvider(RPC))
src = Account.from_key(ANVIL0)
c = w3.eth.contract(address=Web3.to_checksum_address(CONTRAT), abi=ABI)

etapes = []


def verifier(nom, condition, detail=""):
    etapes.append((nom, condition, detail))
    print(f"  [{'OK ' if condition else 'KO '}] {nom}" + (f"   {detail}" if detail else ""))


def virer(vers, montant, gas=21000):
    """
    gas : 21000 suffit pour un compte ordinaire, mais PAS pour abonder la
    cagnotte. receive() emet un evenement Funded, donc l'appel consomme au-dela
    du transfert nu et la transaction echoue silencieusement a 21000.
    """
    tx = {"to": vers, "value": Web3.to_wei(montant, "ether"), "gas": gas,
          "gasPrice": w3.eth.gas_price, "chainId": CHAIN,
          "nonce": w3.eth.get_transaction_count(src.address)}
    w3.eth.wait_for_transaction_receipt(
        w3.eth.send_raw_transaction(src.sign_transaction(tx).raw_transaction))


print(f"contrat {CONTRAT}, manche {c.functions.epoch().call()}\n")

joueur = Account.create()
encaisse = Account.create()          # le "vrai" wallet ou le joueur veut ses gains
virer(joueur.address, 5)
print(f"joueur   {joueur.address}")
print(f"encaisse {encaisse.address}\n")

couleur = random.randint(1, 16)
depart = random.randint(20, 120)
pseudo = "JOUEUR" + str(random.randint(10, 99))
URL = f"http://127.0.0.1:8080/?contract={CONTRAT}&rpc={RPC}&chainid={CHAIN}"

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1600, "height": 1000})
    erreurs = []
    pg.on("pageerror", lambda e: erreurs.append(str(e)))
    pg.on("console", lambda m: erreurs.append(m.text) if m.type == "error" else None)
    pg.add_init_script(f"localStorage.setItem('tw.pk', '{joueur.key.hex()}');"
                       f"localStorage.setItem('tw.color', '{couleur}');")
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(3000)

    print("1. chargement")
    etat = pg.evaluate("() => ({credit: credit.textContent, attract: attract.classList.contains('on'),"
                       " titre: document.title, nom: wName.textContent})")
    verifier("wallet finance, credits affiches", etat["credit"] != "00", f"credit {etat['credit']}")
    verifier("attract mode eteint", not etat["attract"])
    verifier("titre au nouveau nom", "SPLASH" in etat["titre"].upper(), etat["titre"])

    print("\n2. pseudo onchain")
    pg.fill("#inName", pseudo)
    pg.click("#btnName")
    pg.wait_for_timeout(4000)
    onchain = c.functions.names(joueur.address).call().rstrip(b"\x00").decode()
    verifier("pseudo enregistre onchain", onchain == pseudo, f"'{onchain}'")
    verifier("pseudo affiche", pg.locator("#wName").inner_text().strip() == pseudo)

    print("\n3. glisse sur le plateau")
    avant = c.functions.claimsOf(joueur.address).call()
    # On attend que le front soit reellement pret a emettre : sans ca le
    # glisse peut partir avant que les frais de gas soient connus, et chaque
    # pose est alors silencieusement ignoree.
    pg.wait_for_function("() => credit.textContent !== '00'", timeout=15000)
    pg.wait_for_timeout(600)
    box = pg.locator("#board").bounding_box()
    pas = box["width"] / 48
    pg.mouse.move(box["x"] + depart, box["y"] + depart)
    pg.mouse.down()
    for i in range(1, 26):
        pg.mouse.move(box["x"] + depart + i * pas, box["y"] + depart + i * pas)
        pg.wait_for_timeout(45)
    pg.mouse.up()
    pg.wait_for_timeout(6000)

    pg.wait_for_timeout(2000)
    ui = pg.evaluate("() => ({envoyees: +wSent.textContent, echecs: +wErr.textContent})")
    poses = c.functions.claimsOf(joueur.address).call() - avant
    verifier("des poses ont ete envoyees", ui["envoyees"] > 0, f"{ui['envoyees']} envoyees")
    verifier("aucun echec cote front", ui["echecs"] == 0)
    verifier("toutes confirmees onchain", poses == ui["envoyees"], f"{poses} onchain")

    print("\n4. destination des gains")
    pg.fill("#inPayout", encaisse.address)
    pg.click("#btnPayout")
    pg.wait_for_timeout(4000)
    dest = c.functions.destinationOf(joueur.address).call()
    verifier("destination declaree", dest.lower() == encaisse.address.lower())

    print("\n5. classement lisible")
    pg.wait_for_timeout(11000)          # le rafraichissement des pseudos tourne aux 10 s
    classement = pg.locator("#holders").inner_text()
    verifier("le pseudo apparait au classement", pseudo in classement.upper(),
             classement.replace("\n", " | ")[:90])

    pg.screenshot(path=f"{S}/mvp-final.png")
    verifier("aucune erreur console", not erreurs, str(erreurs[:2]))
    b.close()

print("\n6. cloture et paiement")
virer(CONTRAT, 6, gas=60000)
verifier("cagnotte abondee", c.functions.prizePool().call() == Web3.to_wei(6, "ether"))

classement = bot.leaderboard(w3, c)
verifier("le bot voit le pseudo",
         any(p == pseudo for _, _, _, p in classement),
         ", ".join(f"{p or a[:8]}:{t}" for a, t, _, p in classement[:4]))

gagnants = [a for a, _, _, _ in classement[:3]]
parts = [5, 3, 2][:len(gagnants)]
avant_encaisse = w3.eth.get_balance(encaisse.address)
epoque = c.functions.epoch().call()

tx = c.functions.endRound(gagnants, parts).build_transaction({
    "from": src.address, "nonce": w3.eth.get_transaction_count(src.address),
    "chainId": CHAIN, "gas": 600000, "gasPrice": w3.eth.gas_price})
r = w3.eth.wait_for_transaction_receipt(
    w3.eth.send_raw_transaction(src.sign_transaction(tx).raw_transaction))
verifier("endRound reussi", r.status == 1)
verifier("manche suivante", c.functions.epoch().call() == epoque + 1)
verifier("plateau vide", sum(1 for x in c.functions.getColors().call() if x) == 0)
verifier("cagnotte distribuee", c.functions.prizePool().call() < 100)

if joueur.address in gagnants:
    gagne = w3.eth.get_balance(encaisse.address) - avant_encaisse
    verifier("gains verses sur le vrai wallet, pas sur celui du jeu", gagne > 0,
             f"{Web3.from_wei(gagne, 'ether'):.3f} MON")

echecs = [n for n, ok, _ in etapes if not ok]
print(f"\n{'=' * 62}")
print(f"{len(etapes) - len(echecs)}/{len(etapes)} verifications passees")
if echecs:
    print("ECHECS : " + ", ".join(echecs))
    sys.exit(1)
print("MVP valide de bout en bout")
