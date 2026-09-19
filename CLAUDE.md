# Contexte projet — Splash War (Monad Blitz)

## Objectif

Hackathon Monad Blitz sur campus, format court : environ 7 heures de build,
puis un pitch de 3 minutes devant un jury orienté applications grand public.
On construit **Splash War**, un jeu de capture de territoire 100 % onchain.

Une grille 32x32 (1024 cases), une palette de 16 couleurs, pas d'équipes codées.
On choisit une couleur, on clique ou on glisse, chaque case traversée prend la
couleur. N'importe qui peut reprendre n'importe quelle case. **Une case = une
transaction onchain**, sans regroupement et sans délai entre deux poses.

Si la salle s'organise par couleur, les équipes émergent d'elles-mêmes : c'est
un meilleur argument que des équipes codées en dur.

Le but de la démo : faire scanner un QR code à toute la salle, montrer le plateau
qui explose de couleurs au vidéoprojecteur pendant que le compteur de
transactions par seconde monte, puis expliquer pourquoi ce jeu ne peut pas
exister sur une chaîne lente.

## État actuel du repo

```
contracts/SplashWar.sol   contrat complet, commenté, compile en 0.8.24, pas déployé
web/index.html               front complet, un seul fichier, sans build
bot.py                       gen / fund / refill / rank / payout / spam / watch
scripts/deploy.py            compile + déploie + calibre le gas, sans Foundry
tests/                       49 tests e2e sur un EVM py-evm en mémoire
requirements-dev.txt         web3[tester] + pytest, installés dans .venv
README.md                    ordre des opérations et script de pitch
```

**Backend terminé et testé.** 49 tests passent sur un EVM réel en mémoire, sans
réseau ni clé : règles du jeu, palette, manches, cooldown, administration,
récompenses, invariants d'architecture, gas mesuré, et `bot.py` de bout en bout.
Le RPC testnet répond, les deux endpoints renvoient le chain id 10143.

**Il reste le déploiement, qui attend une clé privée approvisionnée dans `.env`,
puis toute la reprise du front, à faire ensemble.**

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
