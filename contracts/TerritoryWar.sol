// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * TerritoryWar - une grille 32x32 que la salle se dispute en temps reel.
 *
 * Regle du jeu : tu cliques une case, elle passe a la couleur de ton equipe.
 * Une case = une transaction. Pas de batch, pas de rollup, pas d'astuce :
 * on envoie une transaction par clic parce que sur Monad on peut se le permettre.
 *
 * Note d'archi a garder pour le pitch :
 * une transaction touche exactement DEUX slots de storage, et les deux sont
 * indexes par des cles independantes (le numero de case, et l'adresse du joueur).
 * Deux joueurs qui cliquent deux cases differentes n'ont aucun etat en commun,
 * donc rien ne force l'execution sequentielle. C'est exactement le cas favorable
 * de l'EVM parallele. On a volontairement supprime tout compteur global
 * (pas de "totalClaims++") : un seul compteur global aurait suffi a serialiser
 * toutes les transactions du jeu sur un seul slot.
 */
contract TerritoryWar {
    // ---------------------------------------------------------------------
    // Constantes
    // ---------------------------------------------------------------------

    uint16 public constant WIDTH = 32;
    uint16 public constant HEIGHT = 32;
    uint16 public constant CELLS = 1024; // WIDTH * HEIGHT
    uint8 public constant TEAMS = 4;

    // ---------------------------------------------------------------------
    // Storage
    // ---------------------------------------------------------------------

    /// Etat d'une case. 20 + 1 + 4 = 25 octets : tient dans UN slot de 32 octets,
    /// donc une seule ecriture disque par capture.
    struct Cell {
        address owner; // dernier joueur a avoir capture la case
        uint8 team; // 1..4
        uint32 epoch; // manche pendant laquelle la case a ete capturee
    }

    /// Etat d'un joueur. 1 + 4 + 8 = 13 octets : un seul slot egalement.
    struct Player {
        uint8 team; // derniere equipe choisie
        uint32 claims; // nombre total de captures (toutes manches confondues)
        uint64 lastBlock; // bloc de la derniere capture, pour le cooldown
    }

    mapping(uint16 => Cell) private _cells;
    mapping(address => Player) public players;

    /// Numero de manche. Un reset incremente ce compteur : toutes les cases
    /// dont l'epoch est perime sont considerees comme vides. Ca evite de devoir
    /// reecrire 1024 slots pour vider le plateau entre deux demos.
    uint32 public epoch = 1;

    /// Nombre de blocs a attendre entre deux captures d'un meme joueur.
    /// 0 = pas de cooldown (recommande pour une demo : zero transaction rejetee,
    /// et le compteur de tx/s monte plus haut).
    /// 2 ou 3 = mode "jeu equitable", empeche un seul bot de peindre le plateau.
    uint64 public cooldownBlocks = 0;

    address public admin;

    // ---------------------------------------------------------------------
    // Evenements : c'est ce que le front ecoute pour se mettre a jour en direct
    // ---------------------------------------------------------------------

    event Claimed(uint32 indexed epoch, uint16 indexed cell, address indexed player, uint8 team);
    event Reset(uint32 indexed epoch);

    // ---------------------------------------------------------------------
    // Erreurs (moins cheres en gas que des require avec message)
    // ---------------------------------------------------------------------

    error BadCell();
    error BadTeam();
    error Cooldown();
    error AlreadyYours();
    error NotAdmin();

    modifier onlyAdmin() {
        if (msg.sender != admin) revert NotAdmin();
        _;
    }

    constructor() {
        admin = msg.sender;
    }

    // ---------------------------------------------------------------------
    // Action principale
    // ---------------------------------------------------------------------

    /**
     * Capture une case pour une equipe.
     * L'equipe est passee a chaque appel : pas d'inscription prealable,
     * donc un nouveau joueur n'a besoin que d'UNE transaction pour entrer
     * dans le jeu. Zero friction pour la salle pendant la demo.
     */
    function claim(uint16 cell, uint8 team) external {
        if (cell >= CELLS) revert BadCell();
        if (team == 0 || team > TEAMS) revert BadTeam();

        Player memory p = players[msg.sender];

        // Cooldown : desactive par defaut (cooldownBlocks == 0).
        if (cooldownBlocks != 0 && p.lastBlock != 0) {
            if (block.number < uint256(p.lastBlock) + uint256(cooldownBlocks)) revert Cooldown();
        }

        uint32 e = epoch;
        Cell storage c = _cells[cell];

        // On refuse de recapturer sa propre case : ca evite de bruler du gas
        // pour rien si l'utilisateur double-clique.
        if (c.epoch == e && c.owner == msg.sender) revert AlreadyYours();

        // Ecriture 1 : la case (slot indexe par le numero de case)
        c.owner = msg.sender;
        c.team = team;
        c.epoch = e;

        // Ecriture 2 : le joueur (slot indexe par son adresse)
        unchecked {
            players[msg.sender] = Player({team: team, claims: p.claims + 1, lastBlock: uint64(block.number)});
        }

        emit Claimed(e, cell, msg.sender, team);
    }

    // ---------------------------------------------------------------------
    // Lectures (gratuites, utilisees par le front)
    // ---------------------------------------------------------------------

    /// Etat complet du plateau : 1024 entiers, 0 = case vide, 1..4 = equipe.
    /// Appele une fois au chargement de la page puis toutes les ~20 secondes
    /// pour resynchroniser, le reste du temps le front suit les evenements.
    function getTeams() external view returns (uint8[] memory teams) {
        teams = new uint8[](CELLS);
        uint32 e = epoch;
        for (uint16 i = 0; i < CELLS; i++) {
            Cell storage c = _cells[i];
            if (c.epoch == e) {
                teams[i] = c.team;
            }
        }
    }

    /// Score par equipe. L'index 0 est inutilise, les scores sont en 1..4.
    function teamScores() external view returns (uint32[5] memory scores) {
        uint32 e = epoch;
        for (uint16 i = 0; i < CELLS; i++) {
            Cell storage c = _cells[i];
            if (c.epoch == e) {
                scores[c.team]++;
            }
        }
    }

    /// Proprietaire actuel d'une case (adresse nulle si la case est vide).
    function ownerOf(uint16 cell) external view returns (address) {
        Cell storage c = _cells[cell];
        return c.epoch == epoch ? c.owner : address(0);
    }

    /// Nombre total de captures d'un joueur, pour un leaderboard individuel.
    function claimsOf(address player) external view returns (uint32) {
        return players[player].claims;
    }

    // ---------------------------------------------------------------------
    // Administration
    // ---------------------------------------------------------------------

    /// Vide le plateau instantanement (une seule ecriture de storage).
    function reset() external onlyAdmin {
        unchecked {
            epoch += 1;
        }
        emit Reset(epoch);
    }

    /// Active / desactive le cooldown en direct pendant la demo.
    function setCooldown(uint64 blocks_) external onlyAdmin {
        cooldownBlocks = blocks_;
    }

    function setAdmin(address newAdmin) external onlyAdmin {
        admin = newAdmin;
    }
}
