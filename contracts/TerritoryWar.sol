// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * TerritoryWar - une grille 32x32 que la salle repeint en temps reel.
 *
 * Regle du jeu : tu choisis une couleur dans une palette de 16, tu cliques ou
 * tu glisses sur la grille, chaque case traversee prend ta couleur.
 * Une case = une transaction. Pas de batch, pas de rollup, pas d'astuce :
 * on envoie une transaction par case parce que sur Monad on peut se le permettre.
 *
 * Il n'y a volontairement PAS d'equipes codees dans le contrat. Chacun joue
 * pour lui, avec la couleur qu'il veut. Si la salle decide de s'organiser par
 * couleur, les equipes emergent d'elles-memes sans une ligne de Solidity.
 *
 * Note d'archi a garder pour le pitch :
 * une transaction touche exactement DEUX slots de storage, et les deux sont
 * indexes par des cles independantes (le numero de case, et l'adresse du joueur).
 * Deux joueurs qui peignent deux cases differentes n'ont aucun etat en commun,
 * donc rien ne force l'execution sequentielle. C'est exactement le cas favorable
 * de l'EVM parallele. On a volontairement supprime tout compteur global
 * (pas de "totalClaims++") : un seul compteur global aurait suffi a serialiser
 * toutes les transactions du jeu sur un seul slot.
 *
 * La palette elle-meme n'est pas onchain : le contrat ne stocke qu'un indice
 * de 1 a 16, le front decide a quoi il ressemble. Changer les teintes ne
 * demande donc aucun redeploiement.
 */
contract TerritoryWar {
    // ---------------------------------------------------------------------
    // Constantes
    // ---------------------------------------------------------------------

    uint16 public constant WIDTH = 32;
    uint16 public constant HEIGHT = 32;
    uint16 public constant CELLS = 1024; // WIDTH * HEIGHT
    uint8 public constant COLORS = 16;

    // ---------------------------------------------------------------------
    // Storage
    // ---------------------------------------------------------------------

    /// Etat d'une case. 20 + 1 + 4 = 25 octets : tient dans UN slot de 32 octets,
    /// donc une seule ecriture disque par capture.
    struct Cell {
        address owner; // dernier joueur a avoir peint la case
        uint8 color; // 1..16, indice dans la palette du front
        uint32 epoch; // manche pendant laquelle la case a ete peinte
    }

    /// Etat d'un joueur. 1 + 4 + 8 = 13 octets : un seul slot egalement.
    struct Player {
        uint8 color; // derniere couleur utilisee
        uint32 claims; // nombre total de cases peintes (toutes manches confondues)
        uint64 lastBlock; // bloc de la derniere pose, pour le cooldown
    }

    mapping(uint16 => Cell) private _cells;
    mapping(address => Player) public players;

    /// Numero de manche. Un reset incremente ce compteur : toutes les cases
    /// dont l'epoch est perime sont considerees comme vides. Ca evite de devoir
    /// reecrire 1024 slots pour vider le plateau entre deux demos.
    uint32 public epoch = 1;

    /// Nombre de blocs a attendre entre deux poses d'un meme joueur.
    /// 0 = pas de cooldown (recommande pour une demo : zero transaction rejetee,
    /// et le compteur de tx/s monte plus haut). C'est ce qui rend le clic
    /// glisse possible : sans cooldown, une seule main peut poser en continu.
    uint64 public cooldownBlocks = 0;

    address public admin;

    // ---------------------------------------------------------------------
    // Evenements : c'est ce que le front ecoute pour se mettre a jour en direct
    // ---------------------------------------------------------------------

    event Claimed(uint32 indexed epoch, uint16 indexed cell, address indexed player, uint8 color);
    event Reset(uint32 indexed epoch);

    // ---------------------------------------------------------------------
    // Erreurs (moins cheres en gas que des require avec message)
    // ---------------------------------------------------------------------

    error BadCell();
    error BadColor();
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
     * Peint une case d'une couleur de la palette.
     * La couleur est passee a chaque appel : pas d'inscription prealable,
     * donc un nouveau joueur n'a besoin que d'UNE transaction pour entrer
     * dans le jeu. Zero friction pour la salle pendant la demo.
     */
    function claim(uint16 cell, uint8 color) external {
        if (cell >= CELLS) revert BadCell();
        if (color == 0 || color > COLORS) revert BadColor();

        Player memory p = players[msg.sender];

        // Cooldown : desactive par defaut (cooldownBlocks == 0).
        if (cooldownBlocks != 0 && p.lastBlock != 0) {
            if (block.number < uint256(p.lastBlock) + uint256(cooldownBlocks)) revert Cooldown();
        }

        uint32 e = epoch;
        Cell storage c = _cells[cell];

        // On refuse de repeindre sa propre case dans la meme couleur : ca evite
        // de bruler du gas pour rien quand le doigt s'attarde sur une case.
        if (c.epoch == e && c.owner == msg.sender && c.color == color) revert AlreadyYours();

        // Ecriture 1 : la case (slot indexe par le numero de case)
        c.owner = msg.sender;
        c.color = color;
        c.epoch = e;

        // Ecriture 2 : le joueur (slot indexe par son adresse)
        unchecked {
            players[msg.sender] = Player({color: color, claims: p.claims + 1, lastBlock: uint64(block.number)});
        }

        emit Claimed(e, cell, msg.sender, color);
    }

    // ---------------------------------------------------------------------
    // Lectures (gratuites, utilisees par le front)
    // ---------------------------------------------------------------------

    /// Etat complet du plateau : 1024 entiers, 0 = case vide, 1..16 = couleur.
    /// Appele une fois au chargement de la page puis toutes les ~20 secondes
    /// pour resynchroniser, le reste du temps le front suit les evenements.
    function getColors() external view returns (uint8[] memory colors) {
        colors = new uint8[](CELLS);
        uint32 e = epoch;
        for (uint16 i = 0; i < CELLS; i++) {
            Cell storage c = _cells[i];
            if (c.epoch == e) {
                colors[i] = c.color;
            }
        }
    }

    /// Nombre de cases par couleur. L'index 0 est inutilise, les scores sont en 1..16.
    /// Recalcule a la lecture, justement pour ne pas avoir de compteur en storage.
    function colorScores() external view returns (uint32[17] memory scores) {
        uint32 e = epoch;
        for (uint16 i = 0; i < CELLS; i++) {
            Cell storage c = _cells[i];
            if (c.epoch == e) {
                scores[c.color]++;
            }
        }
    }

    /// Proprietaire de chaque case : 1024 adresses, adresse nulle si la case
    /// est vide. C'est la base du systeme de recompense : le score qui compte
    /// n'est pas le nombre de cases posees mais le territoire encore detenu
    /// quand la manche se termine. Recalcule integralement a la lecture, donc
    /// toujours aucun compteur en storage et aucune ecriture ajoutee au claim.
    function getOwners() external view returns (address[] memory owners) {
        owners = new address[](CELLS);
        uint32 e = epoch;
        for (uint16 i = 0; i < CELLS; i++) {
            Cell storage c = _cells[i];
            if (c.epoch == e) {
                owners[i] = c.owner;
            }
        }
    }

    /// Proprietaire actuel d'une case (adresse nulle si la case est vide).
    function ownerOf(uint16 cell) external view returns (address) {
        Cell storage c = _cells[cell];
        return c.epoch == epoch ? c.owner : address(0);
    }

    /// Nombre total de cases peintes par un joueur, pour le classement individuel.
    /// Le front s'en sert aussi pour savoir si le slot joueur est deja ecrit,
    /// et ajuster le gas_limit en consequence.
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
