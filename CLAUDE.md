# Contexte projet — Splash War (Monad Blitz Paris, 19/09/2026)

## Etat : LIVRE ET PRESENTE

Le projet a ete pitche et joue en salle. Le plateau a recu plus de 760 cases
d'une vingtaine de joueurs finances automatiquement.

```
site        https://splash-war.vercel.app
depot       https://github.com/vassCaR/splash-war   (public)
contrat     0x458FB580596c971ba54b40244A7Eee90d886dD45   empreinte DD45
reseau      Monad testnet, chain id 10143, bloc de deploiement 63922565
wallet      0x50A4fe41b88B775eCCA324Bc5747fB31A8792526  (admin + financeur)
```

## Le jeu

Grille 48x48 (2304 cases), palette de 32 couleurs, un clic ou un glisse pose
une case. Chaque case est une transaction onchain, sans regroupement. Pas
d'equipes codees : les joueurs choisissent leur couleur, le classement se fait
au nombre de cases posees.

Format retenu pour la demo : **cooperatif**. L'organisateur projette une image,
la salle la reproduit. Le second mode, chacun pour soi, n'a pas ete joue : le
RPC public ne tient pas un concours de clics a vingt personnes.

## Ce qu'il faut savoir avant d'y retoucher

**Le gas est facture sur le gas_limit, pas sur le gas_used.** Toute marge est
payee plein pot. `scripts/deploy.py` calibre les constantes sur une mesure
reelle au deploiement. Mesure Monad : 90330 gas dans le pire cas, contre 71620
sur un EVM local, soit 26 % d'ecart. Les constantes locales feraient mourir
chaque transaction en OutOfGas sur le testnet.

**L'adresse du contrat vit dans `web/contract.json`**, relu sans cache par le
front. Elle n'est plus figee dans le HTML : un onglet ouvert avant un
redeploiement se recale seul. Sans cela, deux joueurs peignent sur deux toiles
differentes en voyant chacun un plateau coherent. Une empreinte de quatre
caracteres est affichee dans l'en-tete pour verifier d'un coup d'oeil.

**Le financement est automatique** via `api/fund.js`, une fonction serverless
Vercel qui credite 0,6 MON a chaque nouveau wallet depuis la reserve. La cle
vit dans les variables d'environnement Vercel, jamais dans le site statique.
Sans ce relais, un joueur arrive avec zero MON et ne peut rien faire.

**Charge RPC** : 0,35 requete par seconde et par telephone en lecture. A vingt
joueurs, 7 req/s mesures, sous la limite d'environ 25 du RPC public. Mais un
concours de clics ajoute une requete par case posee et fait exploser le total.

## Tests

```
63 tests unitaires        EVM py-evm en memoire, sans reseau
tests/audit_e2e.py        22 verifications, navigateur reel contre le testnet
tests/test_fund.mjs       relais de financement, 8 verifications
```

L'invariant du projet est garde par `tests/test_invariants.py` : une pose ne
doit modifier aucun slot fixe du contrat. Un `totalClaims++` ajoute pour un
leaderboard fait echouer ce test, et serialiserait tout le jeu.

## Commandes utiles

```
.venv/bin/python scripts/deploy.py --reset                 vider la toile (admin seul)
.venv/bin/python bot.py rank --par poses --contract 0x...  classement officiel
.venv/bin/python scripts/projection.py image.png           feuille de projection
.venv/bin/python scripts/qr.py https://splash-war.vercel.app/   QR et affiche
.venv/bin/python tests/audit_e2e.py [url]                  audit complet
```

Pas d'emojis dans le code ni dans les reponses. Rien qui mentionne Claude dans
les commits, les README ou les pages publiees.

---

## Stack

- Contrat : Solidity 0.8.24, déployé via Remix (le plus rapide) ou `forge create`
- Front : HTML/CSS/JS vanilla, ethers v6 en UMD depuis jsDelivr, aucune installation, aucun build
- Scripts : Python avec web3.py
- Hébergement du front : fichier statique, `python3 -m http.server` en local, Vercel ou Netlify pour la salle

Je préfère Python pour tout ce qui est script et outillage. Le contrat reste en
Solidity, le front en JS vanilla : pas de framework, pas d'étape de build, le
temps de mise en place ne se rentabilise pas sur 7 heures.

Pas d'emojis dans le code ni dans les réponses.

## Réseau Monad Testnet

| Élément | Valeur |
|---|---|
| Chain ID | 10143 |
| Symbole | MON |
| RPC principal | `https://testnet-rpc.monad.xyz` (environ 25 req/s, partagé) |
| RPC de secours | `https://rpc.ankr.com/monad_testnet` (environ 300 req/10 s) |
| Faucet | `https://faucet.monad.xyz` (cooldown de 12 h par adresse) |
| Explorer | `https://testnet.monadscan.com` (monadexplorer.com redirige vers monadvision.com) |
| Base fee | 100 gwei, codée en dur sur le testnet (mesurée le 19/09/2026) |
| Facturation du gas | sur le `gas_limit`, **pas** sur le `gas_used` |
| `eth_getLogs` | 100 blocs maximum par requête |

## Décisions d'architecture à ne pas casser

Ces choix sont l'argument technique du pitch. Si une modification les remet en
cause, il faut me prévenir explicitement avant de l'appliquer.

**Deux emplacements de stockage par transaction, tous les deux indépendants.**
Une pose écrit la case (indexée par son numéro) et l'état du joueur (indexé
par son adresse). Deux joueurs qui cliquent deux cases différentes n'ont aucun
état commun, donc rien n'oblige l'exécution séquentielle. C'est le cas favorable
de l'EVM parallèle de Monad.

**Aucun compteur global dans le contrat.** Un simple `totalClaims++` ferait
passer toutes les transactions du jeu par un même slot et les sérialiserait,
ce qui annulerait le point précédent. Les scores sont recalculés à la lecture,
en vue ou côté front. Ne jamais ajouter de variable d'état écrite à chaque
transaction.

**Pas de batch.** Une case par transaction. C'est volontaire et c'est le propos.

**Le glissé continu n'est bridé par aucun délai.** C'est le cœur du jeu. Seul un
garde-fou de solde arrête les envois avant que le wallet soit à sec. Conséquence
directe : un navigateur émet 8 à 15 tx/s, trente navigateurs saturent un RPC
public. Une clé RPC dédiée n'est pas optionnelle.

**Reset par numéro de manche.** Un compteur `epoch` invalide les 1024 cases en
une seule écriture au lieu d'en réécrire 1024. Mesuré : vider un plateau plein
coûte le même prix que vider un plateau vide.

**Le système de récompense reste hors du chemin chaud.** La cagnotte est abondée
une fois et distribuée une fois par manche, jamais 1024 fois. `claim()` ne lit ni
n'écrit aucun de ses slots. Le classement n'est pas calculé onchain : il se déduit
de `getOwners()`, donc d'un état déjà stocké. Le score qui compte est le territoire
encore tenu à la fin, pas le nombre de poses.

**`tests/test_invariants.py` garde ces décisions.** Il photographie le storage
avant et après une pose et exige qu'aucun slot fixe ne bouge. Un `totalClaims++`
ajouté "juste pour le leaderboard" fait échouer ce test. Si un test d'invariant
casse, ce n'est pas un détail d'implémentation, c'est la thèse du projet qui tombe.

**Gas adaptatif côté front.** La limite suit l'état réel du slot visé : 43 010 pour
une repeinture, 82 340 pour une case vierge. Comme Monad facture la limite, ça
divise la note par deux sur le cas courant.

**Cooldown à 0 par défaut.** Débit maximum, zéro transaction rejetée pendant la
démo. `setCooldown(3)` existe pour le mode jeu équitable.

**Wallet jetable généré dans le navigateur.** Pas de MetaMask, pas de popup de
signature à chaque clic, sinon personne ne joue au-delà de trois clics. Le nonce
est géré côté client, les frais sont mis en cache, la case est repeinte de façon
optimiste sans attendre la confirmation.

**Lecture par polling de `eth_getLogs`.** Pas de websocket : plus simple, plus
robuste sur un wifi de campus. Resynchronisation complète du plateau via
`getTeams()` toutes les 25 boucles.

## Pièges connus, déjà identifiés

**Le gas est facturé sur le `gas_limit`, pas sur le `gas_used`.** C'est la conséquence
de l'exécution asynchrone : le bloc est voté avant d'être exécuté, donc le protocole ne
peut pas facturer la consommation réelle. Toute marge de gas est payée plein pot. Le
`gas_limit` de 200 000 initialement présent dans le front coûtait 0.0200 MON par clic,
soit 2 clics pour un wallet financé à 0.05 MON : la démo mourait à la deuxième minute.
Il est descendu à 90 000, et `scripts/deploy.py` le recalibre sur le pire cas réel
(`eth_estimateGas` + 15 %) après le déploiement, dans le front comme dans `bot.py`.
Ne jamais remonter cette valeur par précaution.

**Budget MON de la démo.** 0.0043 MON par repeinture, 0.0082 par case vierge
(mesures réelles). Un geste de 32 cases coûte 0.14 MON, donc 0.5 MON par
participant. 30 personnes font 15 MON ; le bot à 30 tx/s brûle 16 MON par minute,
donc en rafales courtes uniquement. Le faucet donne 0.05 MON à un wallet vierge, 2 MON avec un historique
Ethereum mainnet, 5 MON avec le rôle Full Access sur le Discord Monad : un wallet jetable
généré dans le navigateur est vierge, les participants ne peuvent donc pas se servir
eux-mêmes. Prendre le rôle Discord la veille et tirer sur plusieurs adresses.

**`eth_getLogs` plafonné à 100 blocs par requête.** Le front demandait
`fromBlock: cursor+1, toBlock: "latest"` : dès qu'il prenait plus de 100 blocs de retard
(40 secondes, un rate limit suffit), la requête échouait en boucle et le plateau restait
figé définitivement, y compris la resynchronisation. Les requêtes sont maintenant bornées
à 90 blocs, avec saut en avant et resync forcée si le retard dépasse la fenêtre.

**Limites de débit du RPC public.** 25 requêtes par seconde tous utilisateurs
confondus. Trente navigateurs qui interrogent les logs plus un bot qui spamme
saturent immédiatement, et le plateau se fige alors que la chaîne va très bien.
Prévoir de basculer sur Ankr ou une clé gratuite QuickNode/Alchemy.

**Exécution asynchrone de Monad.** Le consensus tourne 3 blocs en avance sur
l'exécution. Un compte fraîchement approvisionné qui avait un solde nul ne peut
pas dépenser tant que le virement n'a pas 3 blocs d'âge, soit environ 1,2 seconde
après le reçu. Concrètement : ne jamais enchaîner `bot.py fund` et `bot.py spam`
sans pause, sinon on voit des rejets pour solde insuffisant alors que le solde
est bien là.

**Faucet limité.** Cooldown de 12 h par adresse : la salle entière ne pourra pas
se servir pendant la démo. Il faut arroser les wallets des participants avec
`bot.py fund --extra <adresses>` depuis un compte pré-approvisionné.

**Reverts.** Le contrat rejette la recapture de sa propre case et le cooldown
non écoulé. Le front doit filtrer ces cas en amont pour ne pas brûler de gas.

## Ce qu'il reste à faire, par ordre de priorité

1. Déployer le contrat : remplir `.env`, puis `.venv/bin/python scripts/deploy.py`
   (le script injecte l'adresse dans le front et calibre le gas tout seul)
2. Valider l'aller-retour complet : clic, transaction, log, repeinture chez un second navigateur
3. Reprendre le front ensemble : identité visuelle maison, retour sonore d'arcade
4. Déployer le front en statique et générer le QR code pour la salle
5. Tester à deux navigateurs simultanés, vérifier le compteur tx/s et le mode `?spectate=1`
6. Seulement ensuite, si le temps le permet : leaderboard individuel, retour sonore, animation de capture

## Méthode de travail

Le temps est la contrainte dominante. Faire marcher avant de faire beau, et
faire beau avant d'ajouter des fonctionnalités. Pas de refactoring tant que la
chaîne complète n'est pas validée en conditions réelles.

Code freeze une heure avant la fin, puis enregistrement d'une vidéo de 45
secondes de la démo qui fonctionne : le wifi d'un campus un jour de hackathon
tombe toujours au pire moment.

Si une piste prend plus de 30 minutes sans résultat visible, me le dire et
proposer un repli plutôt que de continuer à creuser.
