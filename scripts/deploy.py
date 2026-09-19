#!/usr/bin/env python3
"""
deploy.py - compile et deploie TerritoryWar sur Monad testnet, sans Foundry.

    export TW_DEPLOYER_KEY=0x...
    python scripts/deploy.py

Ecrit l'adresse dans deployment.json et l'injecte dans web/index.html
(constante DEFAULTS.CONTRACT) pour que le front marche sans parametre d'url.

Options utiles :
    --no-write-front   ne pas toucher a web/index.html
    --reset            appelle reset() sur un contrat deja deploye
    --cooldown N       appelle setCooldown(N)
"""

import argparse
import json
import os
import re
import sys

try:
    from web3 import Web3
    from eth_account import Account
except ImportError:
    sys.exit("web3 manquant : pip install -r requirements.txt")

try:
    import solcx
except ImportError:
    sys.exit("py-solc-x manquant : pip install -r requirements.txt")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "contracts", "TerritoryWar.sol")
FRONT = os.path.join(ROOT, "web", "index.html")
OUT = os.path.join(ROOT, "deployment.json")

def load_env():
    """
    Charge .env a la racine du projet, sans dependance externe.
    La cle privee reste dans ce fichier, jamais dans une ligne de commande
    ni dans l'historique du shell. .env est deja dans .gitignore.
    """
    path = os.path.join(ROOT, ".env")
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
EXPLORER = "https://testnet.monadscan.com"
SOLC = "0.8.24"


def compile_contract():
    installed = [str(v) for v in solcx.get_installed_solc_versions()]
    if SOLC not in installed:
        print(f"installation de solc {SOLC}...")
        solcx.install_solc(SOLC)
    print(f"compilation de {os.path.relpath(SOURCE, ROOT)} avec solc {SOLC}")
    compiled = solcx.compile_files(
        [SOURCE], output_values=["abi", "bin"],
        solc_version=SOLC, optimize=True, optimize_runs=200,
    )
    key = next(k for k in compiled if k.endswith(":TerritoryWar"))
    art = compiled[key]
    print(f"bytecode {len(art['bin']) // 2} octets")
    return art["abi"], art["bin"]


def connect(rpc):
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        sys.exit("RPC injoignable : " + rpc)
    chain = w3.eth.chain_id
    if chain != CHAIN_ID:
        print(f"attention : chain id {chain}, attendu {CHAIN_ID}")
    return w3


def fees(w3):
    try:
        base = w3.eth.get_block("latest").get("baseFeePerGas") or w3.eth.gas_price
    except Exception:
        base = w3.eth.gas_price
    try:
        tip = w3.eth.max_priority_fee
    except Exception:
        tip = Web3.to_wei(2, "gwei")
    return int(base) * 2 + int(tip), int(tip)


def raw_of(signed):
    return getattr(signed, "raw_transaction", None) or signed.rawTransaction


def load_key(args):
    key = args.key or os.environ.get("TW_DEPLOYER_KEY")
    if not key:
        sys.exit("cle du deployeur manquante : --key 0x... ou export TW_DEPLOYER_KEY=0x...")
    return Account.from_key(key)


def send(w3, acct, tx, label):
    max_fee, tip = fees(w3)
    tx.update({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
        "chainId": CHAIN_ID, "type": 2,
        "maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip,
    })
    if "gas" not in tx:
        # Monad facture le gas_limit : on estime puis on ajoute une marge serree.
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
    cost = tx["gas"] * max_fee
    print(f"{label} : gas_limit {tx['gas']}, cout max "
          f"{Web3.from_wei(cost, 'ether'):.5f} MON")
    h = w3.eth.send_raw_transaction(raw_of(acct.sign_transaction(tx)))
    print(f"  tx {h.hex()}")
    rcpt = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    if rcpt.status != 1:
        sys.exit("transaction echouee")
    return rcpt


def calibrate(w3, acct, address, abi):
    """
    Mesure le cout reel d'une pose et aligne les constantes de gas dessus.

    Sur Monad le gas est facture sur le gas_limit, pas sur le gas_used : chaque
    millier de gas de marge est paye plein pot par tous les joueurs. Le front
    ajuste donc sa limite case par case, selon que le slot vise est deja ecrit
    ou non. On mesure ici le pire cas (case vierge ET joueur vierge, les deux
    slots passent de zero a non-zero) et on en deduit la partie fixe.
    """
    COLD = 22100  # SSTORE d'un slot a zero, tarif EVM
    c = w3.eth.contract(address=address, abi=abi)
    try:
        worst = c.functions.claim(0, 1).estimate_gas({"from": acct.address})
    except Exception as exc:
        print("calibration impossible (" + str(exc)[:70] + "), constantes inchangees")
        return None

    fixed = worst - 2 * COLD
    limit = ((int(worst * 1.15) // 1000) + 1) * 1000
    base = w3.eth.get_block("latest").get("baseFeePerGas") or w3.eth.gas_price
    cher = Web3.from_wei(limit * int(base), "ether")
    pas_cher = Web3.from_wei(int((fixed + 2 * 5000) * 1.15) * int(base), "ether")

    print(f"calibration : pire cas mesure {worst} gas, partie fixe {fixed}")
    print(f"              base fee {Web3.from_wei(base, 'gwei'):.0f} gwei")
    print(f"              case vierge {cher:.5f} MON, repeinture {pas_cher:.5f} MON")
    print(f"              une reserve de 0.5 MON vaut environ "
          f"{int(0.5 / float(pas_cher))} repeintures")

    edits = [
        (FRONT, r"fixed:\s*\d+n", f"fixed: {fixed}n"),
        (os.path.join(ROOT, "bot.py"), r"GAS_LIMIT = [\d_]+", f"GAS_LIMIT = {limit}"),
    ]
    for path, pattern, repl in edits:
        try:
            txt = open(path).read()
            out, n = re.subn(pattern, repl, txt, count=1)
            if n:
                open(path, "w").write(out)
                print(f"              {os.path.relpath(path, ROOT)} mis a jour")
        except FileNotFoundError:
            pass
    return limit


def write_front(address):
    with open(FRONT) as f:
        html = f.read()
    new, n = re.subn(r'(CONTRACT:\s*)"[^"]*"', r'\1"%s"' % address, html, count=1)
    if not n:
        print("adresse non injectee dans le front : motif CONTRACT introuvable")
        return
    with open(FRONT, "w") as f:
        f.write(new)
    print(f"adresse injectee dans {os.path.relpath(FRONT, ROOT)}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rpc", default=RPC_DEFAULT)
    p.add_argument("--key", help="cle privee (ou TW_DEPLOYER_KEY)")
    p.add_argument("--no-write-front", action="store_true")
    p.add_argument("--contract", help="adresse existante, pour --reset / --cooldown")
    p.add_argument("--reset", action="store_true", help="vide le plateau")
    p.add_argument("--cooldown", type=int, help="setCooldown(N)")
    args = p.parse_args()

    w3 = connect(args.rpc)
    acct = load_key(args)
    balance = w3.eth.get_balance(acct.address)
    print(f"deployeur {acct.address}  {Web3.from_wei(balance, 'ether'):.4f} MON")
    if balance == 0:
        sys.exit("solde nul : passe par https://faucet.monad.xyz")

    abi, bytecode = compile_contract()

    if args.reset or args.cooldown is not None:
        addr = args.contract or json.load(open(OUT))["address"]
        c = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=abi)
        if args.reset:
            send(w3, acct, c.functions.reset().build_transaction({"gas": 60000}), "reset()")
            print("plateau vide")
        if args.cooldown is not None:
            send(w3, acct,
                 c.functions.setCooldown(args.cooldown).build_transaction({"gas": 60000}),
                 f"setCooldown({args.cooldown})")
            print(f"cooldown = {args.cooldown} blocs")
        return

    rcpt = send(w3, acct, {"data": "0x" + bytecode}, "deploiement")
    address = Web3.to_checksum_address(rcpt.contractAddress)

    calibrate(w3, acct, address, abi)

    with open(OUT, "w") as f:
        json.dump({"address": address, "chainId": CHAIN_ID, "rpc": args.rpc,
                   "deployer": acct.address, "block": rcpt.blockNumber, "abi": abi},
                  f, indent=2)

    if not args.no_write_front:
        write_front(address)

    print()
    print("contrat   " + address)
    print("explorer  " + f"{EXPLORER}/address/{address}")
    print("front     " + f"http://localhost:8080/?contract={address}")
    print("bot       " + f"python bot.py spam --contract {address} --rate 30")


if __name__ == "__main__":
    main()
