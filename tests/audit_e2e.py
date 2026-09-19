#!/usr/bin/env python3
"""
Audit de bout en bout : navigateur reel, chaine reelle, parcours complet.

    .venv/bin/python tests/audit_e2e.py [url]

Par defaut il vise le serveur local, qui sert exactement les fichiers qui
seront pousses. Passer l'url de production pour auditer ce qui est en ligne.
Couvre l'accueil, le pseudo, les deux modes, le gabarit, la peinture reelle,
la ressemblance, la recharge, la musique et les erreurs console.
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MONAD_CHAIN_ID", "10143")

from web3 import Web3
from eth_account import Account
from playwright.sync_api import sync_playwright
import bot

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080/"
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(RACINE, "deployment.json")))
C, ABI = d["address"], d["abi"]
RPC = "https://testnet-rpc.monad.xyz"

w3 = bot.connect(RPC)
c = w3.eth.contract(address=C, abi=ABI)
admin = Account.from_key(
    open(os.path.join(RACINE, ".env")).read().split("TW_DEPLOYER_KEY=")[1].split()[0])

etapes = []
def verif(nom, ok, detail=""):
    etapes.append((nom, ok))
    print(f"  [{'OK ' if ok else 'KO '}] {nom}" + (f"   {detail}" if detail else ""))

print(f"contrat {C} | manche {c.functions.epoch().call()}")
print(f"cible   {BASE}\n")

joueur = Account.create()
mf, tip = bot.fees(w3)
tx = {"to": joueur.address, "value": Web3.to_wei(0.6, "ether"), "gas": 21000,
      "maxFeePerGas": mf, "maxPriorityFeePerGas": tip, "type": 2, "chainId": 10143,
      "nonce": w3.eth.get_transaction_count(admin.address, "pending")}
w3.eth.wait_for_transaction_receipt(
    w3.eth.send_raw_transaction(bot.raw_of(admin.sign_transaction(tx))), timeout=150)
time.sleep(3)
print(f"joueur {joueur.address} : "
      f"{Web3.from_wei(w3.eth.get_balance(joueur.address),'ether')} MON\n")

pseudo = "AUDIT" + str(random.randint(10, 99))
url = f"{BASE}?contract={C}"

with sync_playwright() as p:
    b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    pg = b.new_page(viewport={"width": 1500, "height": 950})
    err = []
    pg.on("pageerror", lambda e: err.append(str(e)[:130]))
    pg.on("console", lambda m: err.append(m.text[:130]) if m.type == "error" else None)
    pg.add_init_script(f"localStorage.setItem('tw.pk','{joueur.key.hex()}');")
    pg.goto(url, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(4000)

    print("1. ecran d'accueil")
    a = pg.evaluate("""()=>({visible: !document.getElementById('accueil').classList.contains('partie'),
        logo: !!document.querySelector('.accueil .heros'),
        roue: !!document.getElementById('btnReglages')})""")
    verif("accueil affiche au premier passage", a["visible"])
    verif("logo et roue crantee presents", a["logo"] and a["roue"])

    print("\n2. entree en jeu avec pseudo")
    pg.fill("#inPseudoAccueil", pseudo)
    pg.click("#btnStart")
    pg.wait_for_timeout(3500)
    e = pg.evaluate("""()=>({cache: document.getElementById('accueil').classList.contains('partie'),
        pseudo: document.getElementById('wName').textContent,
        audio: TWSound.etat, musique: TWSound.musiqueActive})""")
    verif("accueil ferme", e["cache"])
    verif("pseudo repris", e["pseudo"] == pseudo, e["pseudo"])
    verif("audio debloque par le geste", e["audio"] == "running", e["audio"])
    verif("musique lancee", e["musique"])

    print("\n3. mode cooperatif et gabarit")
    pg.evaluate("()=>document.getElementById('btnModeCoop').click()")
    pg.wait_for_timeout(1200)
    g = pg.evaluate("""()=>({bloc: !document.getElementById('blocCoop').hidden,
        nb: document.querySelectorAll('#listeGabarits .gab').length,
        choisi: document.querySelector('#listeGabarits .gab.on')?.textContent || '',
        detail: document.getElementById('detailCoop').textContent})""")
    verif("bloc coop visible", g["bloc"])
    verif("gabarits charges", g["nb"] >= 5, f"{g['nb']} gabarits")
    verif("un gabarit est selectionne", bool(g["choisi"]), g["choisi"])
    verif("compteur de ressemblance calcule", "/" in g["detail"], g["detail"])

    print("\n4. peinture reelle sur la chaine")
    avant = c.functions.claimsOf(joueur.address).call()
    r0 = pg.evaluate("()=>{const r=ressemblance();return r?r.juste:0}")
    # on peint la ou le gabarit attend quelque chose
    box = pg.locator("#board").bounding_box()
    pas = box["width"] / 48
    cible = pg.evaluate("""()=>{const out=[];for(let i=0;i<2304&&out.length<10;i++)
        if(gabarit&&gabarit[i]&&!board[i])out.push([i%48,(i/48)|0,gabarit[i]]);return out}""")
    verif("cases du modele identifiees", len(cible) >= 5, f"{len(cible)} cases")
    for x, y, couleur in cible[:8]:
        pg.evaluate(f"()=>{{myColor={couleur};store.set('tw.color',{couleur});renderPalette();}}")
        pg.mouse.move(box["x"] + (x + 0.5) * pas, box["y"] + (y + 0.5) * pas)
        pg.mouse.down(); pg.wait_for_timeout(90); pg.mouse.up()
        pg.wait_for_timeout(180)
    pg.wait_for_timeout(9000)

    ui = pg.evaluate("()=>({envoyees:+wSent.textContent, echecs:+wErr.textContent})")
    verif("poses envoyees", ui["envoyees"] >= 5, f"{ui['envoyees']} envoyees")
    verif("aucun echec", ui["echecs"] == 0)
    r1 = pg.evaluate("()=>{const r=ressemblance();return r?r.juste:0}")
    verif("la ressemblance progresse", r1 > r0, f"{r0} -> {r1} cases justes")

    print("\n5. mode chacun pour soi")
    pg.evaluate("()=>document.getElementById('btnModeVersus').click()")
    pg.wait_for_timeout(1500)
    v = pg.evaluate("""()=>({bloc: !document.getElementById('blocVersus').hidden,
        coopCache: document.getElementById('blocCoop').hidden,
        lignes: document.querySelectorAll('#spammeurs .row').length,
        texte: document.getElementById('spammeurs').innerText.slice(0,60)})""")
    verif("bloc versus visible", v["bloc"])
    verif("bloc coop masque", v["coopCache"])
    verif("classement des poses alimente", v["lignes"] >= 1, v["texte"].replace("\n", " "))

    print("\n6. ecran de recharge")
    pg.evaluate("()=>document.getElementById('btnRecharge').click()")
    pg.wait_for_timeout(1000)
    rc = pg.evaluate("""()=>({visible: !document.getElementById('recharge').hidden,
        adresse: document.getElementById('rAddr').textContent,
        etapes: document.querySelectorAll('#recharge .etape').length})""")
    verif("ecran de recharge s'ouvre", rc["visible"])
    verif("adresse du joueur affichee", rc["adresse"].lower() == joueur.address.lower())
    verif("les trois etapes sont la", rc["etapes"] == 3)
    pg.evaluate("()=>document.getElementById('btnFermerRecharge').click()")

    # Le serveur statique local ne gere pas POST : l'appel au relais de
    # financement y echoue forcement en 501. Ce n'est pas un defaut de l'app,
    # le front retombe proprement sur l'ecran manuel. En production le relais
    # repond, donc on ne filtre que ce cas precis.
    bruit = [e for e in err if "501" in e and "POST" in e]
    reels = [e for e in err if e not in bruit]
    verif("aucune erreur console", not reels, str(reels[:2]))
    if bruit:
        print("      (501 sur /api/fund ignore : serveur local sans POST)")
    pg.screenshot(path="/tmp/claude-1000/-home-jean-dev-monad-blitz/cc002d3c-5e76-41e8-a0e4-efa01c1ee78f/scratchpad/audit.png")
    b.close()

print("\n7. verification onchain")
time.sleep(4)
poses = c.functions.claimsOf(joueur.address).call() - avant
verif("poses confirmees onchain", poses >= 5, f"{poses} poses")
nom = c.functions.names(joueur.address).call().rstrip(b"\x00").decode()
verif("pseudo pas ecrit onchain sans transaction", nom == "", f"'{nom}' (attendu vide)")
occupees = sum(1 for x in c.functions.getColors().call() if x)
verif("plateau reflete les poses", occupees >= poses, f"{occupees} cases occupees")

echecs = [n for n, ok in etapes if not ok]
print("\n" + "=" * 60)
print(f"{len(etapes)-len(echecs)}/{len(etapes)} verifications")
if echecs:
    print("ECHECS : " + ", ".join(echecs)); sys.exit(1)
print("AUDIT COMPLET : TOUT PASSE")
