#!/usr/bin/env python3
"""
bot.py - outillage Territory War : wallets jetables, financement, spam, monitoring.

    python bot.py gen   --n 20
    python bot.py fund  --key <cle_privee_source> --amount 0.05
    python bot.py spam  --contract 0x... --rate 30 --teams 1,3
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

RPC_DEFAULT = os.environ.get("MONAD_RPC", "https://testnet-rpc.monad.xyz")
CHAIN_ID = 10143
WALLETS_FILE = os.environ.get("TW_WALLETS", "wallets.json")

# Une capture consomme ~35k de gas en repeinture, ~68k sur une case vierge.
# 90k couvre le pire cas avec de la marge, sans surfacturer les 3/4 des clics.
GAS_LIMIT = 90_000
BLOCKS_BEFORE_SPEND = 3          # retard d'execution Monad
GETLOGS_MAX_RANGE = 100          # plafond du RPC public

SELECTOR = Web3.keccak(text="claim(uint16,uint8)")[:4]
_topic = Web3.keccak(text="Claimed(uint32,uint16,address,uint8)").hex()
CLAIMED_TOPIC = _topic if _topic.startswith("0x") else "0x" + _topic
TEAM_NAMES = {1: "ACID", 2: "MAGENTA", 3: "CYAN", 4: "AMBER"}
W = H = 32


# ----------------------------------------------------------------------
# utilitaires
# ----------------------------------------------------------------------

def connect(rpc):
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        sys.exit("RPC injoignable : " + rpc)
    return w3


def claim_data(cell, team):
    return SELECTOR + cell.to_bytes(32, "big") + team.to_bytes(32, "big")


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

def cmd_fund(args):
    w3 = connect(args.rpc)
    key = args.key or os.environ.get("TW_FUNDER_KEY")
    if not key:
        sys.exit("cle du compte source manquante : --key 0x... ou export TW_FUNDER_KEY=0x...")
    funder = Account.from_key(key)

    targets = []
    if not args.extra_only:
        targets += [wlt["address"] for wlt in load_wallets()]
    targets += [Web3.to_checksum_address(a) for a in (args.extra or [])]
    if not targets:
        sys.exit("aucune adresse a financer")

    amount = Web3.to_wei(args.amount, "ether")
    balance = w3.eth.get_balance(funder.address)
    needed = amount * len(targets)
    print(f"source  {funder.address}  {fmt_mon(balance)}")
    print(f"cibles  {len(targets)} x {args.amount} MON = {fmt_mon(needed)}")
    if balance < needed:
        sys.exit("solde insuffisant sur le compte source")

    if args.skip_funded:
        kept = []
        for addr in targets:
            if w3.eth.get_balance(addr) >= amount // 2:
                continue
            kept.append(addr)
        print(f"{len(targets) - len(kept)} deja approvisionnes, ignores")
        targets = kept
        if not targets:
            return

    max_fee, tip = fees(w3)
    nonce = w3.eth.get_transaction_count(funder.address, "pending")
    hashes = []
    for addr in targets:
        tx = {
            "to": addr, "value": amount, "gas": 21_000,
            "maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip,
            "nonce": nonce, "chainId": CHAIN_ID, "type": 2,
        }
        signed = funder.sign_transaction(tx)
        try:
            h = w3.eth.send_raw_transaction(raw_of(signed))
            hashes.append(h)
            nonce += 1
            print(f"  -> {addr}  {h.hex()}")
        except Exception as exc:
            print(f"  !! {addr}  {exc}")
        time.sleep(args.delay)

    if not hashes:
        return
    print("attente du dernier recu...")
    try:
        w3.eth.wait_for_transaction_receipt(hashes[-1], timeout=90)
    except Exception as exc:
        print("recu non confirme : " + str(exc))

    # Execution asynchrone : le solde n'est pas depensable avant ~3 blocs.
    pause = BLOCKS_BEFORE_SPEND * 0.5 + 1.0
    print(f"pause de {pause:.1f}s (execution asynchrone Monad) avant de pouvoir depenser")
    time.sleep(pause)
    print("wallets prets")


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

    def fire(self, cell, team, max_fee, tip):
        with self.lock:
            nonce = self.nonce
            self.nonce += 1
        tx = {
            "to": self.contract, "data": claim_data(cell, team), "value": 0,
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
    teams = [int(t) for t in args.teams.split(",") if t.strip()]
    if not teams or any(t < 1 or t > 4 for t in teams):
        sys.exit("--teams attend des valeurs entre 1 et 4, ex: 1,3")

    if args.region:
        x0, y0, x1, y1 = (int(v) for v in args.region.split(","))
        x0, x1 = sorted((max(0, x0), min(W - 1, x1)))
        y0, y1 = sorted((max(0, y0), min(H - 1, y1)))
    else:
        x0, y0, x1, y1 = 0, 0, W - 1, H - 1
    cells = [y * W + x for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    print(f"zone {x0},{y0} -> {x1},{y1} ({len(cells)} cases), equipes {teams}")

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

    def shoot(sender, cell, team):
        err = sender.fire(cell, team, state["max_fee"], state["tip"])
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
                        random.choice(cells), random.choice(teams))
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
    per_team = {1: 0, 2: 0, 3: 0, 4: 0}
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
                    # seul 'team' n'est pas indexe : data = 32 octets, equipe
                    # dans le dernier. epoch / cell / player sont dans les topics.
                    data = log["data"]
                    if isinstance(data, str):
                        data = bytes.fromhex(data[2:] if data.startswith("0x") else data)
                    team = data[-1] if data else 0
                    per_team[team] = per_team.get(team, 0) + 1
                    seen.append(now)
                cursor = to_block

            seen = [t for t in seen if time.time() - t < 10]
            tps = len(seen) / 10
            total = sum(per_team.values())
            repartition = "  ".join(
                f"{TEAM_NAMES.get(t, t)} {per_team.get(t, 0)}" for t in (1, 2, 3, 4))
            sys.stdout.write(
                f"\r{time.time()-t0:6.0f}s  bloc {cursor}  {tps:5.1f} tx/s  "
                f"total {total:6d}   {repartition}".ljust(130))
            sys.stdout.flush()
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\narret")


# ----------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Outillage Territory War / Monad")
    p.add_argument("--rpc", default=RPC_DEFAULT, help=f"defaut: {RPC_DEFAULT}")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gen", help="cree des wallets jetables")
    g.add_argument("--n", type=int, default=20)
    g.add_argument("--replace", action="store_true", help="repart de zero")
    g.set_defaults(func=cmd_gen)

    f = sub.add_parser("fund", help="approvisionne les wallets")
    f.add_argument("--key", help="cle privee du compte source (ou TW_FUNDER_KEY)")
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
    s.add_argument("--teams", default="1,2,3,4")
    s.add_argument("--region", help="x0,y0,x1,y1")
    s.add_argument("--duration", type=float, help="secondes, sinon jusqu'a Ctrl-C")
    s.add_argument("--fee-mult", type=int, default=2)
    s.set_defaults(func=cmd_spam)

    w = sub.add_parser("watch", help="compteur tx/s en direct")
    w.add_argument("--contract", required=True)
    w.add_argument("--poll", type=float, default=0.5)
    w.set_defaults(func=cmd_watch)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
