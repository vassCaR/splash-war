/**
 * Relais de financement.
 *
 * Un wallet jetable naît avec zéro MON et ne peut donc rien envoyer. Sans ce
 * relais, un joueur qui scanne le QR code tombe sur un mur. La page appelle
 * cette fonction à l'arrivée, le wallet est crédité, le joueur peint. Il ne
 * voit jamais ni gas, ni solde, ni jeton à insérer.
 *
 * La clé du financeur vit dans les variables d'environnement Vercel et ne
 * quitte jamais le serveur. C'est la différence avec un site statique, qui ne
 * lit jamais ces variables : ici la fonction s'exécute côté Vercel.
 */
import { ethers } from "ethers";

export const config = { runtime: "nodejs" };

const RPC = process.env.MONAD_RPC || "https://testnet-rpc.monad.xyz";
const CHAIN_ID = Number(process.env.MONAD_CHAIN_ID || 10143);

const MONTANT = ethers.parseEther(process.env.TW_FUND_AMOUNT || "0.6");
const SEUIL = ethers.parseEther("0.15");   // au-dessus, le joueur n'a besoin de rien
const PLANCHER = ethers.parseEther("4");   // on garde de quoi cloturer la manche
const PAUSE_ADRESSE = 120_000;             // ms entre deux demandes d'une même adresse
const MAX_PAR_IP = 4;

/* Mémoire de l'instance chaude. Une fonction serverless peut être recyclée,
   donc ces garde-fous sont du bonus : les vraies barrières sont le solde
   onchain du demandeur et le plancher de la réserve, qui eux ne mentent pas. */
const derniereDemande = new Map();
const parIP = new Map();

function refus(res, code, raison) {
  return res.status(code).json({ ok: false, raison });
}

export default async function handler(req, res) {
  // Diagnostic : uniquement des noms de variables et des booleens, jamais une
  // valeur. Sert a verifier que l'environnement arrive bien jusqu'a la fonction.
  if (req.method === "GET") {
    const noms = Object.keys(process.env).filter(k => k.startsWith("TW_") || k.startsWith("MONAD_"));
    return res.status(200).json({
      diagnostic: true,
      variables_tw_visibles: noms,
      funder_defini: Boolean(process.env.TW_FUNDER_KEY),
      deployer_defini: Boolean(process.env.TW_DEPLOYER_KEY),
      longueur_funder: (process.env.TW_FUNDER_KEY || "").length,
      vercel_env: process.env.VERCEL_ENV || null,
    });
  }

  if (req.method !== "POST") return refus(res, 405, "methode");

  const cle = process.env.TW_FUNDER_KEY || process.env.TW_DEPLOYER_KEY;
  if (!cle) return refus(res, 500, "financeur non configure");

  let adresse;
  try {
    const corps = typeof req.body === "string" ? JSON.parse(req.body) : req.body || {};
    adresse = ethers.getAddress(String(corps.address || ""));
  } catch {
    return refus(res, 400, "adresse invalide");
  }

  const maintenant = Date.now();
  const precedent = derniereDemande.get(adresse) || 0;
  if (maintenant - precedent < PAUSE_ADRESSE) return refus(res, 429, "trop tot");

  const ip = (req.headers["x-forwarded-for"] || "").split(",")[0].trim() || "inconnue";
  const vues = parIP.get(ip) || new Set();
  if (!vues.has(adresse) && vues.size >= MAX_PAR_IP) return refus(res, 429, "limite par appareil");

  try {
    const provider = new ethers.JsonRpcProvider(RPC, CHAIN_ID, { staticNetwork: true });
    const financeur = new ethers.Wallet(cle, provider);

    const [soldeJoueur, soldeFinanceur, frais] = await Promise.all([
      provider.getBalance(adresse),
      provider.getBalance(financeur.address),
      provider.getFeeData(),
    ]);

    if (soldeJoueur >= SEUIL) {
      return res.status(200).json({ ok: true, deja: true, solde: soldeJoueur.toString() });
    }
    if (soldeFinanceur < PLANCHER + MONTANT) return refus(res, 503, "reserve epuisee");

    const base = frais.maxFeePerGas ?? frais.gasPrice ?? ethers.parseUnits("100", "gwei");
    const tip = frais.maxPriorityFeePerGas ?? ethers.parseUnits("2", "gwei");

    // Trente arrivées simultanées se disputent le même nonce. On relit le
    // nonce en attente à chaque tentative et on réessaie sur collision.
    let dernierEchec;
    for (let essai = 0; essai < 4; essai++) {
      try {
        const tx = await financeur.sendTransaction({
          to: adresse, value: MONTANT, gasLimit: 21000n,
          maxFeePerGas: base, maxPriorityFeePerGas: tip,
          nonce: await provider.getTransactionCount(financeur.address, "pending"),
        });
        derniereDemande.set(adresse, maintenant);
        vues.add(adresse);
        parIP.set(ip, vues);
        return res.status(200).json({ ok: true, hash: tx.hash, montant: MONTANT.toString() });
      } catch (e) {
        dernierEchec = e;
        const m = String(e?.message || "").toLowerCase();
        if (!m.includes("nonce") && !m.includes("replacement") && !m.includes("already known")) break;
        await new Promise(r => setTimeout(r, 120 + Math.random() * 280));
      }
    }
    return refus(res, 502, String(dernierEchec?.shortMessage || dernierEchec?.message || "envoi impossible").slice(0, 120));
  } catch (e) {
    return refus(res, 502, String(e?.message || e).slice(0, 120));
  }
}
