# Territory War — Monad Blitz

Une grille 32x32 que toute la salle se dispute en direct. Un clic = une transaction onchain.
Pas de batch, pas de signature groupee : on envoie une transaction par clic parce que sur
Monad ca passe en moins d'une seconde.

```
contracts/TerritoryWar.sol   le contrat (environ 150 lignes, tout est commente)
web/index.html               le front, un seul fichier, aucune installation
bot.py                       wallets jetables, financement, spam, monitoring
scripts/deploy.py            compilation + deploiement, sans Foundry
requirements.txt             web3 + py-solc-x
```

---

## Le chiffre a connaitre avant tout le reste

**Sur Monad, le gas est facture sur le `gas_limit`, pas sur le `gas_used`.** C'est une
consequence de l'execution asynchrone : le bloc est vote avant d'etre execute, donc le
protocole ne peut pas facturer ce qui a reellement ete consomme.

Concretement, avec une base fee testnet mesuree a **100 gwei** :

| gas_limit | cout par capture | captures par MON |
|---|---|---|
| 200 000 (valeur naive) | 0.0200 MON | 50 |
| 90 000 (valeur actuelle) | 0.0090 MON | 111 |

`scripts/deploy.py` mesure le pire cas reel avec `eth_estimateGas` juste apres le
deploiement et reecrit `GAS_LIMIT` dans `web/index.html` et `bot.py`. Ne pas remonter
cette valeur "au cas ou" : chaque millier de gas de marge est paye par tous les joueurs.

Budget a prevoir pour la demo :

- un participant qui joue 20 clics consomme environ **0.18 MON**
- 30 participants : environ **5.5 MON**
- le bot a 30 tx/s consomme environ **16 MON par minute** — c'est le poste le plus cher,
  a lancer en rafales courtes, pas en continu

**Le faucet ne donne pas la meme chose a tout le monde** : 0.05 MON pour un wallet vierge,
2 MON pour un wallet ayant un historique sur Ethereum mainnet, 5 MON avec le role Full
Access sur le Discord Monad. Un wallet jetable genere dans le navigateur est vierge, donc
plafonne a 0.05 MON, soit 5 clics : **les participants ne peuvent pas se servir eux-memes**,
c'est toi qui les arroses avec `bot.py fund --extra`.

A faire la veille : prendre le role Discord, puis tirer 5 MON sur deux ou trois adresses
differentes (cooldown de 12 h par adresse).

---

## Ordre des operations (compte 45 minutes)

### 1. Wallet et MON de testnet — la veille

- Reseau : **Monad Testnet**, chain ID **10143**, symbole **MON**
- RPC : `https://testnet-rpc.monad.xyz` — secours : `https://rpc.ankr.com/monad_testnet`
- Faucet : https://faucet.monad.xyz (cooldown 12 h par adresse)
- Explorer : https://testnet.monadscan.com

Deux adresses distinctes : une pour deployer, une pour financer les wallets du bot.

### 2. Installer et deployer

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

export TW_DEPLOYER_KEY=0x...
.venv/bin/python scripts/deploy.py
```

Le script compile avec solc 0.8.24, deploie, calibre le `gas_limit`, ecrit
`deployment.json` et injecte l'adresse directement dans `web/index.html`. Il affiche
l'adresse, le lien explorer et les commandes suivantes toutes pretes.

Variante Remix si le reseau du campus bloque le telechargement de solc : coller
`contracts/TerritoryWar.sol`, compiler en 0.8.24, deployer via Injected Provider.

Variante Foundry :

```bash
forge create contracts/TerritoryWar.sol:TerritoryWar \
  --rpc-url https://testnet-rpc.monad.xyz --private-key $PK --broadcast
```

### 3. Lancer le front

```bash
cd web && python3 -m http.server 8080
```

`http://localhost:8080/` fonctionne directement si tu es passe par `deploy.py`. Sinon
`?contract=0x...` ou le panneau Reglages.

Pour la salle : deposer le dossier `web/` sur Vercel, Netlify ou Cloudflare Pages
(fichier statique, glisser-deposer) et distribuer un QR code vers
`https://ton-url/?contract=0x...`.

Le front genere un **wallet jetable** dans chaque navigateur : aucune extension, aucune
popup de signature. C'est ce qui rend la demo jouable a 30 personnes. Le panneau affiche
le solde en **nombre de clics restants**, l'unite qui compte vraiment.

### 4. Remplir le plateau avec le bot

```bash
.venv/bin/python bot.py gen --n 20
.venv/bin/python bot.py fund --key <ta_cle> --amount 0.2
# attendre 2 s : l'execution Monad a 3 blocs de retard sur le consensus
.venv/bin/python bot.py spam --contract 0x... --rate 30 --teams 1,3 --duration 30
.venv/bin/python bot.py watch --contract 0x...
```

`spam` annonce son debit de combustion en MON/minute et le temps de spam restant avant
que les wallets soient vides. `--region x0,y0,x1,y1` cible une zone : pratique pour
pre-dessiner grossierement un logo avant le pitch.

Pour arroser les wallets des participants (le front affiche leur adresse) :

```bash
.venv/bin/python bot.py fund --key <ta_cle> --extra-only --extra 0xaaa 0xbbb --amount 0.2
```

---

## Les pieges qui tuent la demo

**1. Le gas facture sur le gas_limit.** Voir plus haut. C'est le piege numero un et il ne
ressemble a rien de connu sur les autres chaines EVM.

**2. Les limites du RPC public.** `testnet-rpc.monad.xyz` est partage et plafonne, et
`eth_getLogs` n'accepte que **100 blocs par requete**. Le front borne ses requetes a 90
blocs et saute en avant s'il a pris du retard : sans ce garde-fou, une coupure de 40
secondes fige le plateau definitivement alors que la chaine va tres bien. Si ca sature
quand meme, bascule sur `https://rpc.ankr.com/monad_testnet` dans Reglages, ou prends une
cle gratuite QuickNode / Alchemy le matin meme.

**3. Les wallets vides.** Faucet plafonne a 0.05 MON pour un wallet vierge. Prevois 2 a 3
MON d'avance minimum, et arrose a la main avec `fund --extra`.

**4. L'execution asynchrone.** Un compte fraichement approvisionne ne peut pas depenser
avant environ 1,2 seconde. Ne jamais enchainer `fund` et `spam` sans pause — `fund` fait
la pause tout seul, mais pas si tu l'interromps.

---

## Ce qu'il faut dire au jury

- **Une transaction touche exactement deux slots de storage**, indexes l'un par le numero
  de case, l'autre par l'adresse du joueur. Deux joueurs qui cliquent deux cases
  differentes n'ont aucun etat commun : rien n'oblige a les executer l'une apres l'autre.
  C'est le cas favorable de l'EVM parallele.
- **Aucun compteur global.** Un seul `totalClaims++` aurait suffi a faire passer toutes
  les transactions du jeu par un meme slot et a les serialiser. Les scores sont recalcules
  a la lecture. C'est le detail que peu d'equipes verront.
- **On ne batch pas.** Un clic, une transaction. Sur une chaine a 12 secondes de bloc, ce
  jeu n'existe pas.
- **Le reset est en une seule ecriture** : un compteur de manche invalide les 1024 cases
  d'un coup au lieu de reecrire 1024 slots.
- Si on te cherche sur le cout : le `gas_limit` est calibre a `eth_estimateGas` + 15 %,
  parce que Monad facture la limite et pas la consommation. Ca montre que tu as lu la doc.

Ordre de pitch conseille, 3 minutes :

1. 20 s : le plateau vide au videoprojecteur, en mode `?spectate=1`
2. 30 s : tu fais scanner le QR code a la salle, tu te tais, le plateau explose
3. 60 s : le compteur tx/s, et l'explication des deux slots independants
4. 40 s : l'explorer sur une transaction, une de plus parmi des milliers
5. 30 s : la suite (escouades, mises, saisons)

---

## Reglages de derniere minute

```bash
.venv/bin/python scripts/deploy.py --reset                  # vide le plateau
.venv/bin/python scripts/deploy.py --cooldown 3             # mode jeu equitable
.venv/bin/python scripts/deploy.py --cooldown 0             # debit maximum (defaut demo)
```

Ou depuis Remix avec le wallet qui a deploye : `reset()`, `setCooldown(0)`, `setCooldown(3)`.

---

## Plan B

Des que la demo fonctionne, **enregistre une video de 45 secondes**. Le wifi d'un campus un
jour de hackathon tombe toujours au pire moment, et un jury pardonne une video, jamais un
ecran de chargement.
