import { readFileSync } from "node:fs";
import { ethers } from "ethers";

const env = readFileSync(new URL("../.env", import.meta.url), "utf8");
process.env.TW_FUNDER_KEY = env.split("TW_FUNDER_KEY=")[1].split(/\s/)[0];

const { default: handler } = await import("../api/fund.js");

function fausseReponse() {
  const r = { code: 0, corps: null };
  r.status = c => { r.code = c; return r; };
  r.json = o => { r.corps = o; return r; };
  return r;
}
const appel = (body, ip = "1.2.3.4", method = "POST") =>
  handler({ method, body, headers: { "x-forwarded-for": ip } }, fausseReponse());

const provider = new ethers.JsonRpcProvider("https://testnet-rpc.monad.xyz", 10143, { staticNetwork: true });
const joueur = ethers.Wallet.createRandom();
let ok = 0, ko = 0;
const v = (nom, cond, det = "") => { cond ? ok++ : ko++;
  console.log(`  [${cond ? "OK " : "KO "}] ${nom}${det ? "   " + det : ""}`); };

console.log("1. garde-fous");
v("methode GET refusee", (await appel({}, "1.1.1.1", "GET")).code === 405);
v("adresse invalide refusee", (await appel({ address: "pas-une-adresse" })).code === 400);
v("corps vide refuse", (await appel({})).code === 400);

console.log("\n2. financement reel");
console.log("   joueur", joueur.address);
const r1 = await appel({ address: joueur.address });
v("financement accepte", r1.code === 200 && r1.corps?.ok, JSON.stringify(r1.corps).slice(0, 90));

if (r1.corps?.hash) {
  await provider.waitForTransaction(r1.corps.hash, 1, 120000);
  const solde = await provider.getBalance(joueur.address);
  v("MON recus", solde > 0n, ethers.formatEther(solde) + " MON");

  console.log("\n3. protection contre la repetition");
  const r2 = await appel({ address: joueur.address });
  v("deuxieme demande immediate bloquee", r2.code === 429, JSON.stringify(r2.corps));

  const r3 = await appel({ address: joueur.address }, "9.9.9.9");
  v("deja finance : refus sans depense", r3.corps?.deja === true || r3.code === 429,
    JSON.stringify(r3.corps).slice(0, 70));
}

console.log("\n4. limite par appareil");
let bloque = false;
for (let i = 0; i < 6; i++) {
  const r = await appel({ address: ethers.Wallet.createRandom().address }, "5.5.5.5");
  if (r.code === 429 && r.corps?.raison === "limite par appareil") { bloque = true; break; }
}
v("plafond par appareil applique", bloque);

console.log(`\n${ok}/${ok + ko} verifications`);
process.exit(ko ? 1 : 0);
