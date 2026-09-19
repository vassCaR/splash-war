#!/usr/bin/env python3
"""
bot.py - outillage Splash War : wallets jetables, financement, spam, monitoring.

    python bot.py gen   --n 20
    python bot.py fund  --key <cle_privee_source> --amount 0.05
    python bot.py spam   --contract 0x... --rate 30 --colors 4,9
    python bot.py refill --contract 0x... --amount 0.3
    python bot.py rank   --contract 0x...
    python bot.py payout --contract 0x... --shares 5,3,2
    python bot.py watch --contract 0x...

Specificites Monad prises en compte ici :
  - le gas est facture sur le gas_limit, pas sur le gas_used : on serre le
    gas_limit au plus juste, sinon chaque transaction coute 3 a 4 fois trop cher
  - l'execution est asynchrone (3 blocs de retard sur le consensus) : un compte
    fraichement approvisionne ne peut pas depenser immediatement, d'ou l'attente
    apres 'fund'
  - eth_getLogs est plafonne a 100 blocs par requete
"""

import argparse
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

try:
    from web3 import Web3
    from eth_account import Account
except ImportError:
    sys.exit("web3 manquant : pip install -r requirements.txt")


def load_env(path=None):
    """
    Charge .env a la racine du projet, sans dependance externe.
    La cle privee reste dans ce fichier, jamais dans une ligne de commande
    ni dans l'historique du shell. .env est deja dans .gitignore.
    """
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


load_env()

RPC_DEFAULT = os.environ.get("MONAD_RPC", "https://testnet-rpc.monad.xyz")
CHAIN_ID = int(os.environ.get("MONAD_CHAIN_ID", "10143"))
WALLETS_FILE = os.environ.get("TW_WALLETS", "wallets.json")

# Une capture consomme ~35k de gas en repeinture, ~68k sur une case vierge.
# 90k couvre le pire cas avec de la marge, sans surfacturer les 3/4 des clics.
GAS_LIMIT = 104000
BLOCKS_BEFORE_SPEND = 3          # retard d'execution Monad
GETLOGS_MAX_RANGE = 100          # plafond du RPC public

SELECTOR = Web3.keccak(text="claim(uint16,uint8)")[:4]
# ABI minimale : juste ce dont l'outillage a besoin, pour ne pas dependre
# d'une recompilation. deployment.json fournit l'ABI complete si elle existe.
ABI = [
    {"name": "getOwners", "type": "function", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "address[]"}]},
    {"name": "claimsOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "player", "type": "address"}], "outputs": [{"type": "uint32"}]},
    {"name": "prizePool", "type": "function", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "uint256"}]},
    {"name": "epoch", "type": "function", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "uint32"}]},
    {"name": "namesOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "who", "type": "address[]"}], "outputs": [{"type": "bytes32[]"}]},
    {"name": "destinationOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "player", "type": "address"}], "outputs": [{"type": "address"}]},
    {"name": "endRound", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "winners", "type": "address[]"},
                {"name": "shares", "type": "uint32[]"}], "outputs": []},
]

_topic = Web3.keccak(text="Claimed(uint32,uint16,address,uint8)").hex()
CLAIMED_TOPIC = _topic if _topic.startswith("0x") else "0x" + _topic
COLOR_NAMES = ["", "ACID", "LIME", "TEAL", "CYAN", "AZUR", "INDIGO", "VIOLET",
               "MAUVE", "MAGENTA", "ROSE", "ROUGE", "ORANGE", "AMBRE", "JAUNE",
               "SABLE", "BLANC"]
COLORS = 16
W = H = 48   # doit suivre WIDTH/HEIGHT du contrat


# ----------------------------------------------------------------------
# utilitaires
# ----------------------------------------------------------------------

def connect(rpc):
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        sys.exit("RPC injoignable : " + rpc)
    return w3


def claim_data(cell, color):
    return SELECTOR + cell.to_bytes(32, "big") + color.to_bytes(32, "big")


def raw_of(signed):
    # web3 v7 expose raw_transaction, v6 rawTransaction
    return getattr(signed, "raw_transaction", None) or signed.rawTransaction


def load_wallets():
    if not os.path.exists(WALLETS_FILE):
        sys.exit(f"{WALLETS_FILE} absent : lance d'abord 'python bot.py gen --n 20'")
    with open(WALLETS_FILE) as f:
        return json.load(f)["wallets"]


def fees(w3, mult=2):
    """maxFeePerGas / maxPriorityFeePerGas, avec un multiplicateur de securite."""
    try:
        base = w3.eth.get_block("latest").get("baseFeePerGas") or w3.eth.gas_price
    except Exception:
        base = w3.eth.gas_price
    try:
        tip = w3.eth.max_priority_fee
    except Exception:
        tip = Web3.to_wei(2, "gwei")
    return int(base) * mult + int(tip), int(tip)


def fmt_mon(wei):
    return f"{Web3.from_wei(wei, 'ether'):.4f} MON"


# ----------------------------------------------------------------------
# gen
# ----------------------------------------------------------------------

def cmd_gen(args):
    existing = []
    if os.path.exists(WALLETS_FILE) and not args.replace:
        existing = load_wallets()
        print(f"{len(existing)} wallets deja presents, on complete "
              f"(--replace pour repartir de zero)")

    fresh = []
    while len(existing) + len(fresh) < args.n:
        acct = Account.create()
        fresh.append({"address": acct.address, "key": acct.key.hex()})

    wallets = existing + fresh
    with open(WALLETS_FILE, "w") as f:
        json.dump({"wallets": wallets}, f, indent=2)
    os.chmod(WALLETS_FILE, 0o600)

    print(f"{len(fresh)} nouveaux wallets, {len(wallets)} au total dans {WALLETS_FILE}")
    for wlt in fresh[:5]:
        print("  " + wlt["address"])
    if len(fresh) > 5:
        print(f"  ... et {len(fresh) - 5} autres")


# ----------------------------------------------------------------------
# fund
# ----------------------------------------------------------------------

def funders_from(args, w3):
    """Comptes sources, tries du plus garni au plus pauvre, avec leurs soldes."""
    raw = args.key or os.environ.get("TW_FUNDER_KEY") or os.environ.get("TW_DEPLOYER_KEY")
    if not raw:
        sys.exit("cle source manquante : --key 0x...[,0x...] ou TW_FUNDER_KEY dans .env")
    accounts = [Account.from_key(k.strip()) for k in raw.split(",") if k.strip()]
    balances = {a.address: w3.eth.get_balance(a.address) for a in accounts}
    accounts.sort(key=lambda a: balances[a.address], reverse=True)
    return accounts, balances


def send_funds(w3, funders, balances, targets, amount_wei, delay=0.05):
    """
    Repartit les virements sur les comptes sources, le plus garni d'abord.
    Le faucet Monad plafonne par adresse : une reserve de plusieurs dizaines de
    MON est forcement eclatee sur plusieurs comptes.
    """
    max_fee, tip = fees(w3)
    frais = 21_000 * max_fee           # Monad facture le gas_limit, ici 21000 pile
    unitaire = amount_wei + frais
    reserve = sum(balances.values())
    if reserve < unitaire * len(targets):
        sys.exit("reserve insuffisante : il manque "
                 + fmt_mon(unitaire * len(targets) - reserve))

    plan, i = [], 0
    for f in funders:
        part = targets[i:i + int(balances[f.address] // unitaire)]
        if part:
            plan.append((f, part))
            i += len(part)
        if i >= len(targets):
            break

    nonces = {f.address: w3.eth.get_transaction_count(f.address, "pending") for f, _ in plan}
    hashes = []
    for funder, part in plan:
        for addr in part:
            tx = {
                "to": addr, "value": amount_wei, "gas": 21_000,
                "maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip,
                "nonce": nonces[funder.address], "chainId": CHAIN_ID, "type": 2,
            }
            try:
                h = w3.eth.send_raw_transaction(raw_of(funder.sign_transaction(tx)))
                hashes.append(h)
                nonces[funder.address] += 1
                print(f"  -> {addr}  {h.hex()}")
            except Exception as exc:
                print(f"  !! {addr}  {str(exc)[:100]}")
            time.sleep(delay)

    if not hashes:
        return 0
    print("attente du dernier recu...")
    try:
        w3.eth.wait_for_transaction_receipt(hashes[-1], timeout=90)
    except Exception as exc:
        print("recu non confirme : " + str(exc)[:100])
    pause = BLOCKS_BEFORE_SPEND * 0.5 + 1.0
    print(f"pause de {pause:.1f}s (execution asynchrone Monad) avant de pouvoir depenser")
    time.sleep(pause)
    return len(hashes)


def cmd_fund(args):
    w3 = connect(args.rpc)
    funders, balances = funders_from(args, w3)
    for f in funders:
        print(f"source  {f.address}  {fmt_mon(balances[f.address])}")
    if len(funders) > 1:
        print(f"reserve totale {fmt_mon(sum(balances.values()))}")

    targets = []
    if not args.extra_only:
        targets += [wlt["address"] for wlt in load_wallets()]
    targets += [Web3.to_checksum_address(a) for a in (args.extra or [])]
    if not targets:
        sys.exit("aucune adresse a financer")

    amount = Web3.to_wei(args.amount, "ether")
    if args.skip_funded:
        kept = [a for a in targets if w3.eth.get_balance(a) < amount // 2]
        if len(kept) != len(targets):
            print(f"{len(targets) - len(kept)} deja approvisionnes, ignores")
        targets = kept
        if not targets:
            return

    print(f"cibles  {len(targets)} x {args.amount} MON")
    print(f"{send_funds(w3, funders, balances, targets, amount, args.delay)} wallets prets")


# ----------------------------------------------------------------------
# refill
# ----------------------------------------------------------------------

def scan_players(w3, contract, since=None, chunk=GETLOGS_MAX_RANGE):
    """
    Adresses ayant pose au moins une case, extraites des logs Claimed.
    C'est ce qui permet de recharger la salle sans demander son adresse a
    personne : chaque joueur s'est deja identifie par ses propres transactions.
    """
    head = w3.eth.block_number
    start = since if since is not None else max(0, head - 5000)
    seen, block = {}, start
    print(f"lecture des logs, blocs {start} a {head} "
          f"({(head - start) // chunk + 1} requetes)")
    while block <= head:
        to = min(head, block + chunk - 1)
        try:
            logs = w3.eth.get_logs({"address": contract, "topics": [CLAIMED_TOPIC],
                                    "fromBlock": block, "toBlock": to})
        except Exception as exc:
            print("  RPC: " + str(exc)[:90])
            time.sleep(0.5)
            block = to + 1
            continue
        for log in logs:
            # player est le 3e topic indexe : 32 octets dont les 20 derniers
            topic = log["topics"][3]
            topic = topic.hex() if hasattr(topic, "hex") else str(topic)
            seen_addr = Web3.to_checksum_address("0x" + topic[-40:])
            seen[seen_addr] = seen.get(seen_addr, 0) + 1
        block = to + 1
    return seen


def cmd_refill(args):
    """Recharge les wallets des joueurs reperes dans les logs."""
    w3 = connect(args.rpc)
    contract = Web3.to_checksum_address(args.contract)
    funders, balances = funders_from(args, w3)
    for f in funders:
        print(f"source  {f.address}  {fmt_mon(balances[f.address])}")

    since = args.since
    if since is None and os.path.exists("deployment.json"):
        try:
            since = json.load(open("deployment.json")).get("block")
        except Exception:
            pass

    players = scan_players(w3, contract, since)
    if not players:
        print("aucun joueur repere dans cette fenetre de blocs")
        return
    print(f"{len(players)} joueurs reperes")

    seuil = Web3.to_wei(args.min, "ether")
    amount = Web3.to_wei(args.amount, "ether")
    a_sec = []
    for addr, poses in sorted(players.items(), key=lambda kv: -kv[1]):
        solde = w3.eth.get_balance(addr)
        if solde < seuil:
            a_sec.append(addr)
            print(f"  {addr}  {fmt_mon(solde):>12}  {poses:4d} poses  -> recharge")
    if not a_sec:
        print("personne sous le seuil, rien a faire")
        return

    print(f"{len(a_sec)} wallets a recharger de {args.amount} MON")
    if args.dry_run:
        print("--dry-run : rien n'a ete envoye")
        return
    print(f"{send_funds(w3, funders, balances, a_sec, amount, args.delay)} wallets recharges")



# ----------------------------------------------------------------------
# rank / payout
# ----------------------------------------------------------------------

def contract_of(w3, address):
    abi = ABI
    if os.path.exists("deployment.json"):
        try:
            abi = json.load(open("deployment.json")).get("abi") or ABI
        except Exception:
            pass
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)


def leaderboard(w3, contract, avec_poses=True):
    """
    Classement par territoire detenu, recalcule a la lecture.

    Le score qui compte n'est pas le nombre de cases posees mais celles encore
    tenues a la fin : peindre tot ne sert a rien si on se fait recouvrir.
    Le nombre de poses reste affiche a cote, comme mesure d'effort.

    Renvoie une liste de (adresse, tenu, poses, pseudo).
    """
    owners = contract.functions.getOwners().call()
    tenu = {}
    for addr in owners:
        if addr and int(addr, 16) != 0:
            tenu[addr] = tenu.get(addr, 0) + 1
    classement = sorted(tenu.items(), key=lambda kv: -kv[1])
    adresses = [a for a, _ in classement]

    # Les pseudos en une seule lecture : un appel par joueur saturerait le RPC.
    pseudos = {}
    try:
        for addr, brut in zip(adresses, contract.functions.namesOf(adresses).call()):
            nom = brut.rstrip(b"\x00").decode("utf-8", "replace")
            if nom:
                pseudos[addr] = nom
    except Exception:
        pass

    sortie = []
    for addr, n in classement:
        poses = 0
        if avec_poses:
            try:
                poses = contract.functions.claimsOf(addr).call()
            except Exception:
                poses = 0
        sortie.append((addr, n, poses, pseudos.get(addr, "")))
    return sortie


def cmd_rank(args):
    w3 = connect(args.rpc)
    c = contract_of(w3, args.contract)
    classement = leaderboard(w3, c)
    if not classement:
        print("plateau vide, personne ne tient de territoire")
        return
    try:
        pot = c.functions.prizePool().call()
        print(f"manche {c.functions.epoch().call()}, cagnotte {fmt_mon(pot)}")
    except Exception:
        pass
    total = sum(n for _, n, _, _ in classement)
    nommes = sum(1 for _, _, _, p in classement if p)
    print(f"{len(classement)} joueurs ({nommes} avec pseudo), "
          f"{total} cases tenues sur 1024")
    print(f"{'#':>3}  {'joueur':<20} {'adresse':<44} {'tenu':>6} {'poses':>6}  {'garde':>6}")
    for i, (addr, tenu, poses, pseudo) in enumerate(classement[:args.top], start=1):
        garde = f"{tenu / poses * 100:4.0f} %" if poses else "     -"
        print(f"{i:>3}  {pseudo[:20]:<20} {addr:<44} {tenu:>6} {poses:>6}  {garde:>6}")


def cmd_payout(args):
    """Cloture la manche : distribue la cagnotte aux N premiers, puis reset."""
    w3 = connect(args.rpc)
    key = args.key or os.environ.get("TW_DEPLOYER_KEY") or os.environ.get("TW_FUNDER_KEY")
    if not key:
        sys.exit("cle admin manquante : --key 0x... ou TW_DEPLOYER_KEY dans .env")
    admin = Account.from_key(key)
    c = contract_of(w3, args.contract)

    pot = c.functions.prizePool().call()
    if pot == 0:
        sys.exit("cagnotte vide : envoie des MON a l'adresse du contrat d'abord")

    classement = leaderboard(w3, c, avec_poses=False)
    if not classement:
        sys.exit("plateau vide, aucun gagnant a designer")

    parts = [int(x) for x in args.shares.split(",") if x.strip()]
    gagnants = [a for a, _, _, _ in classement[:len(parts)]]
    parts = parts[:len(gagnants)]
    total = sum(parts)

    print(f"cagnotte {fmt_mon(pot)}, {len(gagnants)} gagnants")
    for i, (addr, part) in enumerate(zip(gagnants, parts), start=1):
        _, tenu, _, pseudo = classement[i - 1]
        try:
            dest = c.functions.destinationOf(addr).call()
        except Exception:
            dest = addr
        vers = "" if dest.lower() == addr.lower() else f"  -> {dest}"
        etiquette = pseudo or addr
        print(f"  {i}. {etiquette:<24} {tenu:>4} cases  "
              f"{fmt_mon(pot * part // total):>12}{vers}")

    if args.dry_run:
        print("--dry-run : rien n'a ete envoye")
        return

    max_fee, tip = fees(w3)
    fn = c.functions.endRound(gagnants, parts)
    tx = fn.build_transaction({
        "from": admin.address,
        "nonce": w3.eth.get_transaction_count(admin.address, "pending"),
        "chainId": CHAIN_ID, "type": 2,
        "maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip,
    })
    tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.3)
    h = w3.eth.send_raw_transaction(raw_of(admin.sign_transaction(tx)))
    print(f"endRound  tx {h.hex()}")
    rcpt = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    if rcpt.status != 1:
        sys.exit("endRound a echoue")
    print(f"cagnotte distribuee, nouvelle manche {c.functions.epoch().call()}")


# ----------------------------------------------------------------------
# spam
# ----------------------------------------------------------------------

class Sender:
    """Un wallet jetable, avec son nonce gere localement."""

    def __init__(self, w3, key, contract):
        self.w3 = w3
        self.acct = Account.from_key(key)
        self.contract = contract
        self.lock = threading.Lock()
        self.nonce = w3.eth.get_transaction_count(self.acct.address, "pending")
        self.sent = 0
        self.failed = 0
        self.dead = False

    def fire(self, cell, color, max_fee, tip):
        with self.lock:
            nonce = self.nonce
            self.nonce += 1
        tx = {
            "to": self.contract, "data": claim_data(cell, color), "value": 0,
            "gas": GAS_LIMIT, "maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip,
            "nonce": nonce, "chainId": CHAIN_ID, "type": 2,
        }
        try:
            self.w3.eth.send_raw_transaction(raw_of(self.acct.sign_transaction(tx)))
            self.sent += 1
        except Exception as exc:
            self.failed += 1
            msg = str(exc).lower()
            if "funds" in msg or "balance" in msg:
                self.dead = True
            # nonce desynchronise : on se recale sur la chaine
            try:
                with self.lock:
                    self.nonce = self.w3.eth.get_transaction_count(
                        self.acct.address, "pending")
            except Exception:
                pass
            return str(exc)[:110]
        return None


def cmd_spam(args):
    w3 = connect(args.rpc)
    contract = Web3.to_checksum_address(args.contract)
    colors = [int(t) for t in args.colors.split(",") if t.strip()]
    if not colors or any(c < 1 or c > COLORS for c in colors):
        sys.exit(f"--colors attend des valeurs entre 1 et {COLORS}, ex: 4,9")

    if args.region:
        x0, y0, x1, y1 = (int(v) for v in args.region.split(","))
        x0, x1 = sorted((max(0, x0), min(W - 1, x1)))
        y0, y1 = sorted((max(0, y0), min(H - 1, y1)))
    else:
        x0, y0, x1, y1 = 0, 0, W - 1, H - 1
    cells = [y * W + x for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    print(f"zone {x0},{y0} -> {x1},{y1} ({len(cells)} cases), couleurs "
          + ", ".join(COLOR_NAMES[c] for c in colors))

    wallets = load_wallets()
    senders, vides = [], 0
    for wlt in wallets:
        if w3.eth.get_balance(wlt["address"]) < Web3.to_wei(0.002, "ether"):
            vides += 1
            continue
        senders.append(Sender(w3, wlt["key"], contract))
    if not senders:
        sys.exit("aucun wallet approvisionne : lance 'python bot.py fund' puis attends 2s")
    print(f"{len(senders)} wallets actifs" + (f", {vides} vides ignores" if vides else ""))

    max_fee, tip = fees(w3, mult=args.fee_mult)
    base = w3.eth.get_block("latest").get("baseFeePerGas") or w3.eth.gas_price
    unit = int(base) * GAS_LIMIT          # Monad facture gas_limit * prix effectif
    burn = Web3.from_wei(unit * int(args.rate) * 60, "ether")
    total = sum(w3.eth.get_balance(s.acct.address) for s in senders)
    print(f"base fee {Web3.from_wei(base, 'gwei'):.0f} gwei, gas_limit {GAS_LIMIT} "
          f"-> {fmt_mon(unit)} par capture")
    print(f"a {args.rate:.0f} tx/s cela consomme {burn:.2f} MON par minute ; "
          f"reserve disponible {fmt_mon(total)} "
          f"(environ {total / unit / max(args.rate, 1) / 60:.1f} min de spam)")

    stop = threading.Event()
    state = {"max_fee": max_fee, "tip": tip, "last_err": ""}

    def refresh_fees():
        while not stop.wait(15):
            try:
                state["max_fee"], state["tip"] = fees(w3, mult=args.fee_mult)
            except Exception:
                pass

    def report():
        t0 = time.time()
        prev = 0
        while not stop.wait(1.0):
            sent = sum(s.sent for s in senders)
            failed = sum(s.failed for s in senders)
            alive = sum(0 if s.dead else 1 for s in senders)
            line = (f"\r{time.time()-t0:6.0f}s  envoyees {sent:6d}  "
                    f"{sent-prev:4d} tx/s  echecs {failed:4d}  wallets {alive}/{len(senders)}")
            if state["last_err"]:
                line += "  | " + state["last_err"]
            sys.stdout.write(line.ljust(140))
            sys.stdout.flush()
            prev = sent

    threading.Thread(target=refresh_fees, daemon=True).start()
    threading.Thread(target=report, daemon=True).start()

    pool = ThreadPoolExecutor(max_workers=min(64, max(8, len(senders) * 2)))
    interval = 1.0 / args.rate
    deadline = time.time() + args.duration if args.duration else None
    next_t = time.time()
    i = 0

    def shoot(sender, cell, color):
        err = sender.fire(cell, color, state["max_fee"], state["tip"])
        if err:
            state["last_err"] = err

    try:
        while deadline is None or time.time() < deadline:
            now = time.time()
            if next_t > now:
                time.sleep(next_t - now)
            alive = [s for s in senders if not s.dead]
            if not alive:
                print("\ntous les wallets sont vides, arret")
                break
            pool.submit(shoot, alive[i % len(alive)],
                        random.choice(cells), random.choice(colors))
            i += 1
            next_t += interval
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        pool.shutdown(wait=False)
        sent = sum(s.sent for s in senders)
        failed = sum(s.failed for s in senders)
        print(f"\n{sent} transactions envoyees, {failed} echecs")


# ----------------------------------------------------------------------
# watch
# ----------------------------------------------------------------------

def cmd_watch(args):
    w3 = connect(args.rpc)
    contract = Web3.to_checksum_address(args.contract)
    topic = CLAIMED_TOPIC
    cursor = w3.eth.block_number
    seen = []
    per_color = {}
    t0 = time.time()
    print(f"ecoute de {contract} a partir du bloc {cursor}. Ctrl-C pour arreter.")

    try:
        while True:
            head = w3.eth.block_number
            if head > cursor:
                to_block = min(head, cursor + GETLOGS_MAX_RANGE)
                try:
                    logs = w3.eth.get_logs({
                        "address": contract, "topics": [topic],
                        "fromBlock": cursor + 1, "toBlock": to_block,
                    })
                except Exception as exc:
                    sys.stdout.write("\rRPC: " + str(exc)[:110].ljust(120))
                    time.sleep(1.0)
                    cursor = w3.eth.block_number
                    continue
                now = time.time()
                for log in logs:
                    # seule 'color' n'est pas indexee : data = 32 octets, la
                    # couleur dans le dernier. Le reste est dans les topics.
                    data = log["data"]
                    if isinstance(data, str):
                        data = bytes.fromhex(data[2:] if data.startswith("0x") else data)
                    color = data[-1] if data else 0
                    per_color[color] = per_color.get(color, 0) + 1
                    seen.append(now)
                cursor = to_block

            seen = [t for t in seen if time.time() - t < 10]
            tps = len(seen) / 10
            total = sum(per_color.values())
            top = sorted(per_color.items(), key=lambda kv: -kv[1])[:4]
            repartition = "  ".join(
                f"{COLOR_NAMES[c] if c < len(COLOR_NAMES) else c} {n}" for c, n in top)
            sys.stdout.write(
                f"\r{time.time()-t0:6.0f}s  bloc {cursor}  {tps:5.1f} tx/s  "
                f"total {total:6d}   {repartition}".ljust(130))
            sys.stdout.flush()
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\narret")


# ----------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Outillage Splash War / Monad")
    p.add_argument("--rpc", default=RPC_DEFAULT, help=f"defaut: {RPC_DEFAULT}")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gen", help="cree des wallets jetables")
    g.add_argument("--n", type=int, default=20)
    g.add_argument("--replace", action="store_true", help="repart de zero")
    g.set_defaults(func=cmd_gen)

    f = sub.add_parser("fund", help="approvisionne les wallets")
    f.add_argument("--key", help="cle(s) privee(s) source, separees par des virgules (ou TW_FUNDER_KEY dans .env)")
    f.add_argument("--amount", type=float, default=0.2,
               help="MON par wallet (0.2 = environ 22 captures)")
    f.add_argument("--extra", nargs="*", help="adresses supplementaires a arroser")
    f.add_argument("--extra-only", action="store_true",
                   help="ne financer que les adresses de --extra")
    f.add_argument("--skip-funded", action="store_true",
                   help="ignorer les adresses deja approvisionnees")
    f.add_argument("--delay", type=float, default=0.05, help="pause entre deux envois")
    f.set_defaults(func=cmd_fund)

    s = sub.add_parser("spam", help="envoie des captures en continu")
    s.add_argument("--contract", required=True)
    s.add_argument("--rate", type=float, default=30, help="transactions par seconde")
    s.add_argument("--colors", default="1,4,9,13",
                   help=f"indices 1..{COLORS} separes par des virgules")
    s.add_argument("--region", help="x0,y0,x1,y1")
    s.add_argument("--duration", type=float, help="secondes, sinon jusqu'a Ctrl-C")
    s.add_argument("--fee-mult", type=int, default=2)
    s.set_defaults(func=cmd_spam)

    r = sub.add_parser("refill", help="recharge les joueurs reperes dans les logs")
    r.add_argument("--contract", required=True)
    r.add_argument("--key", help="cle(s) privee(s) source (ou TW_FUNDER_KEY dans .env)")
    r.add_argument("--min", type=float, default=0.08,
                   help="seuil de recharge en MON (defaut 0.08, environ 18 repeintures)")
    r.add_argument("--amount", type=float, default=0.3)
    r.add_argument("--since", type=int, help="bloc de depart (defaut: deployment.json)")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--delay", type=float, default=0.05)
    r.set_defaults(func=cmd_refill)

    k = sub.add_parser("rank", help="classement par territoire tenu")
    k.add_argument("--contract", required=True)
    k.add_argument("--top", type=int, default=15)
    k.set_defaults(func=cmd_rank)

    o = sub.add_parser("payout", help="distribue la cagnotte et cloture la manche")
    o.add_argument("--contract", required=True)
    o.add_argument("--key", help="cle admin (ou TW_DEPLOYER_KEY dans .env)")
    o.add_argument("--shares", default="5,3,2",
                   help="parts des gagnants, dans l'ordre (defaut 5,3,2)")
    o.add_argument("--dry-run", action="store_true")
    o.set_defaults(func=cmd_payout)

    w = sub.add_parser("watch", help="compteur tx/s en direct")
    w.add_argument("--contract", required=True)
    w.add_argument("--poll", type=float, default=0.5)
    w.set_defaults(func=cmd_watch)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
