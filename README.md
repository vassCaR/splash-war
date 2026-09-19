# Territory War — Monad Blitz

Une grille 32x32 que toute la salle repeint en direct. Tu choisis une couleur
dans une palette de 16, tu cliques ou tu glisses, chaque case traversee prend ta
couleur. **Une case = une transaction onchain.** Pas de batch, pas de delai,
pas de signature a chaque geste.

Il n'y a pas d'equipes codees. Chacun joue pour lui. Si la salle s'organise par
couleur, les equipes emergent d'elles-memes.

```
contracts/TerritoryWar.sol   le contrat, tout est commente
web/index.html               le front, un seul fichier, aucune installation
bot.py                       gen / fund / refill / rank / payout / spam / watch
scripts/deploy.py            compile, deploie, calibre le gas, sans Foundry
tests/                       49 tests e2e sur un EVM en memoire
```

---

## Le chiffre a connaitre avant tout le reste

**Sur Monad, le gas est facture sur le `gas_limit`, pas sur le `gas_used`.**
C'est une consequence de l'execution asynchrone : le bloc est vote avant d'etre
execute, donc le protocole ne peut pas facturer ce qui a reellement ete
consomme. Toute marge de gas est payee plein pot, par tout le monde.

Couts reels mesures (`tests/test_invariants.py`), base fee testnet a 100 gwei :

| situation | gas mesure | limite envoyee | cout |
|---|---|---|---|
| case vierge, joueur vierge | 71 551 | 82 340 | 0.0082 MON |
| case vierge, joueur connu | 54 463 | 62 675 | 0.0063 MON |
| **case deja peinte, joueur connu** (cas courant) | **37 491** | **43 010** | **0.0043 MON** |

Le front ajuste sa limite case par case selon ce qu'il sait deja du plateau :
une case deja peinte a forcement son slot non nul, donc son ecriture coute le
tarif a chaud. Ca divise la note par deux sur le cas courant. `scripts/deploy.py`
recalibre ces constantes sur une mesure `eth_estimateGas` reelle juste apres le
deploiement. Ne jamais les remonter "au cas ou".

**Budget de la demo.** Un geste en travers du plateau, 32 cases, coute 0.14 MON.
Compte **0.5 MON par participant** (environ 115 cases) soit 15 MON pour 30
personnes. Le bot, lui, brule 16 MON par minute a 30 tx/s : en rafales courtes
uniquement, et surtout pas en continu.

**Le faucet ne donne pas la meme chose a tout le monde** : 0.05 MON pour un
wallet vierge, 2 MON avec un historique Ethereum mainnet, 5 MON avec le role
Full Access sur le Discord Monad. Les wallets jetables generes dans le
navigateur sont vierges par construction, donc **les participants ne peuvent pas
se servir eux-memes**. C'est toi qui les arroses, avec `bot.py refill`.

A faire la veille : prendre le role Discord, puis tirer sur deux ou trois
adresses differentes (cooldown de 12 h par adresse).

---

## Ordre des operations

### 1. Installer

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # 49 tests, aucun reseau requis
```

### 2. Deployer

```bash
cp .env.example .env    # puis remplir TW_DEPLOYER_KEY
.venv/bin/python scripts/deploy.py
```

Le script compile en solc 0.8.24, deploie, calibre le gas sur une mesure reelle,
ecrit `deployment.json` et injecte l'adresse dans `web/index.html`. Il affiche
ensuite les commandes suivantes toutes pretes.

La cle reste dans `.env`, jamais sur une ligne de commande ni dans l'historique
du shell. `.env` est dans `.gitignore`.

Variante Remix si le reseau du campus bloque le telechargement de solc : coller
`contracts/TerritoryWar.sol`, compiler en 0.8.24, deployer via Injected Provider.

### 3. Lancer le front

```bash
cd web && python3 -m http.server 8080
```

`http://localhost:8080/` marche directement apres `deploy.py`. Sinon
`?contract=0x...`, ou le panneau Reglages.

Pour la salle : deposer `web/` sur Vercel, Netlify ou Cloudflare Pages et
distribuer un QR code vers `https://ton-url/?contract=0x...`.
Mode projecteur : `?spectate=1`.

### 4. Faire vivre la partie

```bash
# recharger les joueurs sans leur demander leur adresse :
# leurs transactions les ont deja identifies
.venv/bin/python bot.py refill --contract 0x... --min 0.08 --amount 0.3

# voir qui mene
.venv/bin/python bot.py rank --contract 0x...

# abonder la cagnotte : un simple virement a l'adresse du contrat

# cloturer : paie les gagnants et vide le plateau en une transaction
.venv/bin/python bot.py payout --contract 0x... --shares 5,3,2 --dry-run
.venv/bin/python bot.py payout --contract 0x... --shares 5,3,2
```

Plan B si la salle est vide : `gen`, `fund`, puis
`spam --contract 0x... --rate 30 --colors 4,9 --duration 30`.
`spam` annonce son debit de combustion en MON par minute et le temps restant
avant que les wallets soient a sec.

---

## Le systeme de recompense

Le score qui compte n'est **pas** le nombre de cases posees, c'est le territoire
encore tenu quand la manche se termine. Peindre tot ne sert a rien si on se fait
recouvrir : c'est ce qui cree la tension dans les dernieres secondes.

Le nombre de poses reste compte a cote, comme mesure d'effort. Il ne coute rien :
il est stocke dans le meme slot que l'etat du joueur, qui est ecrit de toute
facon.

La cagnotte est abondee par un simple virement a l'adresse du contrat, par
n'importe qui. `endRound` la distribue au prorata de parts fournies par l'admin,
puis cloture la manche. Le paiement est direct ; si une adresse refuse les fonds,
son du est mis de cote et elle le retire elle-meme avec `withdraw()` — une
adresse recalcitrante ne peut pas bloquer la distribution des autres.

**Rien de tout cela ne touche au chemin chaud.** `claim()` ne lit ni n'ecrit
aucun slot de la cagnotte. Le classement n'est pas calcule onchain : il se
deduit de `getOwners()`, donc d'un etat deja stocke. Compter les points en
storage aurait coute un compteur global, exactement ce qu'on evite.

---

## Les pieges qui tuent la demo

**1. Le gas facture sur le gas_limit.** Voir plus haut. Ca ne ressemble a rien
de connu sur les autres chaines EVM.

**2. Le RPC public.** `eth_getLogs` n'accepte que **100 blocs par requete** —
verifie, 500 renvoie `413`. Le front borne a 90 blocs et saute en avant s'il a
pris du retard : sans ce garde-fou, une coupure de 40 secondes fige le plateau
definitivement alors que la chaine va tres bien.

Surtout : **le glisse continu n'est bride par aucun delai**, donc un navigateur
emet 8 a 15 tx/s. Trente navigateurs saturent instantanement un RPC public
plafonne a 25 req/s. **Une cle QuickNode ou Alchemy gratuite n'est plus
optionnelle**, a prendre le matin meme. Repli immediat :
`https://rpc.ankr.com/monad_testnet`.

**3. Les wallets vides.** Faucet plafonne a 0.05 MON pour un wallet vierge.
`bot.py refill` est la reponse : il lit les logs, repere les joueurs et recharge
ceux qui sont sous le seuil, sans que personne ait a donner son adresse.

**4. L'execution asynchrone.** Un compte fraichement approvisionne ne peut pas
depenser avant environ 1,2 seconde. `fund` et `refill` font la pause tout seuls.

---

## Ce qu'il faut dire au jury

- **Une transaction touche exactement deux slots de storage**, indexes l'un par
  le numero de case, l'autre par l'adresse du joueur. Deux joueurs qui peignent
  deux cases differentes n'ont aucun etat commun : rien n'oblige a les executer
  l'une apres l'autre. C'est le cas favorable de l'EVM parallele.
  `tests/test_invariants.py` le verifie en photographiant le storage avant et
  apres une pose : aucun slot fixe ne bouge.
- **Aucun compteur global.** Un seul `totalClaims++` aurait suffi a faire passer
  toutes les transactions du jeu par un meme slot et a les serialiser. Meme le
  classement et la cagnotte restent hors du chemin chaud. C'est le detail que
  peu d'equipes verront.
- **On ne batch pas.** Une case, une transaction. Sur une chaine a 12 secondes
  de bloc, ce jeu n'existe pas.
- **Le reset est en une seule ecriture** : un compteur de manche invalide les
  1024 cases d'un coup. Mesure : vider un plateau plein coute le meme prix que
  vider un plateau vide.
- **Le gas_limit est calibre sur une mesure**, parce que Monad facture la limite
  et pas la consommation. Le front l'ajuste meme case par case.

Ordre de pitch conseille, 3 minutes :

1. 20 s : le plateau vide au videoprojecteur, en `?spectate=1`
2. 30 s : tu fais scanner le QR code, tu te tais, le plateau explose
3. 60 s : le compteur tx/s, et l'explication des deux slots independants
4. 40 s : l'explorer sur une transaction, une de plus parmi des milliers
5. 30 s : `payout`, la cagnotte tombe chez les gagnants, le plateau se vide

---

## Reglages de derniere minute

```bash
.venv/bin/python scripts/deploy.py --reset          # vide le plateau
.venv/bin/python scripts/deploy.py --cooldown 3     # mode jeu equitable
.venv/bin/python scripts/deploy.py --cooldown 0     # debit maximum (defaut)
```

---

## Plan B

Des que la demo fonctionne, **enregistre une video de 45 secondes**. Le wifi d'un
campus un jour de hackathon tombe toujours au pire moment, et un jury pardonne
une video, jamais un ecran de chargement.
