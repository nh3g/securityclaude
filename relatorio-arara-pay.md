# Relatório de segurança — Arara Pay (lab)

**Candidato:** Enzo Augusto Ferreira
**Data:** 07/10/2026
**Escopo:** cinco arquivos em `src/` (`auth.ts`, `db.ts`, `merchants.controller.ts`, `reports.controller.ts`, `main.ts`). Todas as provas foram executadas contra a instância local em `http://localhost:3000`, banco em memória, sem nenhum sistema real envolvido.

---

## Resumo executivo

A API tem uma cadeia crítica que termina em dinheiro saindo. A verificação de token aceita `alg:none`, então qualquer pessoa — sem conta e sem senha — forja a identidade de qualquer lojista. E o endpoint que troca a conta de recebimento (payout) decide de quem é a conta pelo **corpo** da requisição, não pelo token. Juntos, os dois permitem redirecionar o recebimento de qualquer lojista para a conta do fraudador, com o aviso por e‑mail desligado na mesma chamada e sem nenhum registro de quem alterou.

Em paralelo, qualquer token lê o cadastro completo de qualquer lojista — incluindo **senha em texto plano**, `api_key` e `webhook_secret` (que, de quebra, é o mesmo para todos). A primeira coisa a corrigir é a autorização da troca de payout junto com a verificação do JWT, no mesmo deploy: uma sem a outra deixa o caminho crítico aberto.

Tudo abaixo foi reproduzido contra a instância em execução; as saídas coladas são reais (transcrição completa em `evidencias/evidencias-terminal.txt`).

---

## Metodologia e ambiente

Leitura dos cinco arquivos para levantar os pontos suspeitos, depois subida do lab (`npm install && npm start`, Node 22) e execução de cada ataque com `curl`, confirmando o efeito no estado da aplicação (lendo o cadastro antes e depois, conferindo o log do servidor). Os tokens forjados (`alg:none`, HS256 assinado com o segredo do código, e um token expirado) foram gerados com um script pequeno de HMAC, sem bibliotecas externas, para a prova ser auditável — está em `evidencias/mktok.js`.

Não usei Burp Suite: para um alvo que é revisão de código + API REST, o `curl` com a saída colada é prova mais limpa e reproduzível, e é exatamente o formato que o enunciado pede ("o comando `curl` (ou httpie, ou script)… cole a saída"). Quem quiser repetir no Burp é só mandar as mesmas requisições pelo Repeater.

---

## Ranking de correção

Ordem da que eu corrigiria primeiro para a última. **Critério:** peso maior para dinheiro saindo agora, depois facilidade de exploração (precisa de credencial?) e alcance (quantos lojistas). Falha que só fica grave combinada com outra herda a urgência da cadeia.

| # | Falha | Severidade | Por que nessa posição |
|---|---|---|---|
| 1 | Troca de payout sem checar dono (BOLA) | **Crítica** | É a ação que move dinheiro. Um campo no corpo decide a vítima. |
| 2 | JWT aceita `alg:none` | **Crítica** | Transforma a #1 em ataque sem conta nenhuma. Vai junto da #1. |
| 3 | Vazamento do cadastro + senha em texto plano | **Crítica** | Entrega senha, `api_key` e `webhook_secret` de todos. Takeover em massa. |
| 4 | Segredo do JWT fixo no código | Alta | Caminho de forja independente do `alg:none`. Exige rotacionar segredo. |
| 5 | Token sem expiração / `ignoreExpiration` | Alta | Qualquer token vazado vale para sempre. |
| 6 | `webhook_secret` igual para todos | Alta | Permite forjar "pagamento aprovado" de outro lojista. |
| 7 | Token e parâmetros em log (debug → CloudWatch) | Média | Canal de vazamento que alimenta a #3 e a #5. |
| 8 | Path traversal no relatório | Média | Entrada do cliente monta o caminho do arquivo sem normalizar. |
| 9 | Aviso ao lojista desligável pelo chamador | Média | Deixa a fraude silenciosa. Agrava a #1. |
| 10 | Login sem rate limit e sem MFA | Baixa | Força bruta de senha fraca. Não é o caminho mais curto aqui. |
| 11 | Sem trilha de auditoria (`payout_log` nunca escrito) | Baixa | Não é explorável sozinha, mas impede responder "alguém já usou isso?". |

Observações menores (M1–M4) no fim da seção de achados; não mudam o ranking.

---

## Achados

### 1. Troca de payout sem validar titularidade — BOLA · Crítica
**Onde:** `merchants.controller.ts`, `trocarPayout()`, linhas 22–53.

**O que é.** O endpoint `POST /v1/merchants/payout-account` pega o `merchant_id` do **corpo** da requisição e atualiza a conta de recebimento daquele id. Nunca confere se o token pertence ao lojista que está sendo alterado (linha 28: `const merchantId = body.merchant_id;`). Qualquer chamador autenticado troca a conta de qualquer lojista.

**Prova.** Atacante é o `m_4821` (login legítimo). Alvo é o `m_0093` (saldo R$ 48.200,00).

```bash
# conta de payout do m_0093 ANTES:  237 / 0001 / 12345-6 / 11222333000181

curl -s -i -X POST localhost:3000/v1/merchants/payout-account \
  -H "Authorization: Bearer $TOKEN_m4821" \
  -d '{"merchant_id":"m_0093","banco":"999","agencia":"6666",
       "conta":"00000-0","cpf_cnpj":"00000000000000","notify":false}'
# HTTP/1.1 201 Created

# conta de payout do m_0093 DEPOIS: 999 / 6666 / 00000-0 / 00000000000000  (persistido)
```

> Detalhe que vale citar na defesa: o corpo da resposta devolve o registro do lojista **como estava antes** do `UPDATE` (o objeto é lido antes da escrita, linha 30 e seguintes). Por isso a prova confirma a troca relendo o cadastro depois, não pela resposta do POST.

**Impacto na Arara.** É o pior tipo de falha para um gateway: o dinheiro do lojista cai na conta do fraudador. Com um laço sobre os ids dos lojistas, o atacante reescreve o payout da base inteira antes do próximo ciclo de liquidação e desvia tudo que seria repassado. Nos três lojistas do lab são R$ 163.000 em saldo; em produção é o volume de cada lojista por ciclo. O prejuízo é da Arara duas vezes: perde o dinheiro e ainda precisa indenizar o lojista lesado, porque a falha é de controle da plataforma, não do cliente.

**Conserto.** O id a alterar tem que vir do token (`claims.sub`), não do corpo. Se a API precisar que uma conta‑mãe opere sobre sub‑lojistas, valida‑se explicitamente que `claims.sub` tem permissão sobre aquele `merchant_id`, em vez de confiar no campo. **Não quebra integradores:** o chamador legítimo só altera a própria conta, então para ele `merchant_id` já é igual ao `sub` — exigir essa igualdade é compatível com o contrato atual. Dá para fazer em duas fases: primeiro só logar e alertar quando `sub ≠ merchant_id`, depois bloquear. Somar a isso: reautenticação/2FA para mudar payout e gravar na `payout_log`.

### 2. Verificação do JWT aceita `alg:none` · Crítica
**Onde:** `auth.ts`, `lerToken()`, linhas 14–26.

**O que é.** A função lê o cabeçalho do token para decidir como verificar. Se o atacante manda `alg:none`, o código pula a assinatura e aceita o payload como verdade (linhas 21–26) — ou seja, o atacante escolhe não ter a assinatura checada. Dá para forjar token para qualquer `sub` sem conhecer segredo nenhum.

**Prova.**
```bash
# token forjado: header {"alg":"none","typ":"JWT"}, payload {"sub":"m_0093"}, sem assinatura
# eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJtXzAwOTMifQ.

curl -s localhost:3000/v1/merchants/m_0093 -H "Authorization: Bearer $TOKEN_NONE"
# { "id":"m_0093", "senha":"arara123", "api_key":"sk_live_m0093_8f2a1c",
#   "webhook_secret":"whsec_plataforma_unico", ... }   -> 200 OK
```

Encadeado com o #1, troca de payout **sem nenhuma credencial** — token forjado com `sub` arbitrário:
```bash
curl -s -X POST localhost:3000/v1/merchants/payout-account \
  -H "Authorization: Bearer $TOKEN_NONE_ARBITRARIO" \
  -d '{"merchant_id":"m_5117","banco":"001","agencia":"0001","conta":"13337-0", ...}'
# HTTP 201  -> m_5117 agora com conta 13337-0
```

**Impacto na Arara.** Sozinho já é bypass total de autenticação. Combinado com o #1, o atacante não precisa sequer de uma conta de lojista para desviar o recebimento de todo mundo. É o que eleva o #1 de "qualquer lojista cadastrado" para "qualquer pessoa na internet".

**Conserto.** Nunca deixar o token dizer como ele deve ser verificado. Remover a leitura manual do cabeçalho e o ramo `alg:none`, e chamar `jwt.verify` com a lista de algoritmos travada em `['HS256']` — a lib rejeita o resto, inclusive `none`. Não quebra integradores: token emitido de verdade é HS256 e continua valendo; só param os tokens forjados.

### 3. Cadastro completo exposto + senha em texto plano · Crítica
**Onde:** `merchants.controller.ts`, `consultar()` linhas 55–63 e a resposta de `trocarPayout` (linha 52); `db.ts` (coluna `senha`, texto plano, e comparação `m.senha !== body.senha` no login).

**O que é.** `GET /v1/merchants/:id` devolve a linha inteira do lojista para qualquer token (sem checar dono), e a resposta inclui `senha`, `api_key` e `webhook_secret`. A senha é guardada em texto plano — nunca deveria sair do banco, muito menos pela API.

**Prova.** Enumeração da base inteira com um único token legítimo:
```
m_0093 | senha=arara123  | api_key=sk_live_m0093_8f2a1c | whsec=whsec_plataforma_unico
m_4821 | senha=senha2024 | api_key=sk_live_m4821_3b9e7d | whsec=whsec_plataforma_unico
m_5117 | senha=mudar123  | api_key=sk_live_m5117_c1d4f0 | whsec=whsec_plataforma_unico
```

**Impacto na Arara.** Com um único token (ou um `alg:none` do #2), o atacante varre a base e coleta senha, chave de API e segredo de webhook de todos. Senha em texto plano: quem lê o banco, um dump ou um backup já tem as credenciais, sem quebrar hash — e, com reuso de senha, o estrago passa da Arara. É credencial e dado de cliente vazando em massa, com peso de LGPD.

**Conserto.** A API devolve só os campos que o cliente precisa (DTO: id, nome, e‑mail, payout mascarado, saldo) e nunca senha/`api_key`/`webhook_secret`. Enforce de dono no `GET /:id` (igual ao #1). Senha com hash forte (bcrypt/argon2); migração sem logout: no próximo login com a senha legada, regravar com hash. Rotacionar `api_key`s e `webhook_secret`s já expostos. Se algum integrador faz parse do corpo inteiro, versionar o endpoint (v2).

### 4. Segredo do JWT fixo no código · Alta
**Onde:** `auth.ts`, linha 4, `JWT_SECRET = 'arara-2024'`.

**O que é.** O segredo que assina os tokens está no fonte. Quem tiver o repositório (ou um vazamento dele) assina tokens HS256 válidos para qualquer lojista — caminho de forja independente do `alg:none`. Pior: `arara-2024` é fraco e adivinhável mesmo sem acesso ao código.

**Prova.**
```bash
# token HS256 assinado pelo atacante com o segredo 'arara-2024' do código
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  localhost:3000/v1/merchants/m_5117 -H "Authorization: Bearer $HS256_arara2024"
# HTTP 200  (aceito como legítimo)

# contraprova: mesma estrutura, assinada com segredo errado
# HTTP 500  (rejeitado — ver M1 sobre por que 500 e não 401)
```

**Impacto na Arara.** Qualquer pessoa com o segredo (repo, histórico de git, CI, log) emite tokens de qualquer lojista indefinidamente e, encadeado com #1 e #3, desvia dinheiro e colhe credenciais.

**Conserto.** Segredo sai do código para um cofre/variável de ambiente, valor forte e aleatório (≥ 32 bytes). Rotação com identificador de chave (`kid`) e janela aceitando chave antiga e nova durante a virada, para não deslogar todo mundo. Integração servidor‑a‑servidor usa `api_key`, não JWT.

### 5. Token sem expiração e `ignoreExpiration` ligado · Alta
**Onde:** `auth.ts`, `assinarToken()` linha 8 (assina sem `exp`) e `lerToken()` linha 31 (`ignoreExpiration: true`).

**O que é.** O token é assinado sem `exp` e a verificação ainda passa `ignoreExpiration:true`. Token não expira nunca, e mesmo um com `exp` no passado é aceito.

**Prova.**
```bash
# payload do token legítimo — não existe campo exp:
# {"sub":"m_4821","iat":1791397791}

# token com exp lá em 2023 é aceito do mesmo jeito:
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  localhost:3000/v1/merchants/m_5117 -H "Authorization: Bearer $TOKEN_EXPIRADO"
# HTTP 200  (deveria ser 401)
```

**Impacto na Arara.** Qualquer token que vaze uma vez (ver #7) vale para sempre. Não há janela que feche sozinha nem como deixar o token velho morrer. Revogação vira um problema manual que o sistema não resolve hoje.

**Conserto.** Token de acesso curto (ex.: 15 min) com `exp`, remover `ignoreExpiration`. Para manter sessão, refresh token revogável. Período de transição e orientar backends a usar `api_key`.

### 6. `webhook_secret` igual para todos os lojistas · Alta
**Onde:** `db.ts`, `seed()` — `whsec_plataforma_unico` nos três lojistas.

**O que é.** Todo lojista compartilha o mesmo segredo de webhook. Como ele ainda vaza pela resposta da API (#3), qualquer um que leu um cadastro assina webhooks como a plataforma para outro lojista.

**Impacto na Arara.** Webhook é o que avisa o lojista que "o pagamento foi aprovado". Com segredo único, o fraudador forja essa notificação para o sistema de um lojista e dispara a entrega de um produto por uma venda nunca paga. Prejuízo direto ao lojista e disputa/chargeback contra a Arara.

**Conserto.** Segredo único por lojista, aleatório, guardado cifrado, nunca retornado pela API depois de criado (exibido só na geração). Assinar e verificar cada webhook com o segredo daquele lojista. Rotação com janela aceitando antigo e novo.

### 7. Token e parâmetros caindo no log (debug → CloudWatch) · Média
**Onde:** `reports.controller.ts`, linha 15.

**O que é.** O endpoint de conciliação loga o header `Authorization` inteiro e todos os parâmetros, em nível debug que vai para o CloudWatch.

**Prova.** Linha real do log do servidor após uma requisição autenticada:
```
DEBUG [reports] conciliacao auth=Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJtXzQ4MjEi...4Z1P params={"arquivo":"out.csv"}
```

**Impacto na Arara.** O token inteiro fica guardado no log. Quem acessa o CloudWatch (time interno amplo, integrador de observabilidade, vazamento de logs) replica a sessão. Como o token não expira (#5), cada linha de log é uma credencial permanente.

**Conserto.** Nunca logar o header de autorização nem corpo/parâmetros crus. Registrar no máximo o `sub` verificado e um id de requisição. Baixar o nível do log, redação de segredos no pipeline, restringir acesso/retenção do CloudWatch. Rotacionar tokens já logados.

### 8. Path traversal no relatório de conciliação · Média
**Onde:** `reports.controller.ts`, linha 18, `` `relatorios/${q.arquivo}` ``.

**O que é.** O caminho do arquivo é montado concatenando a entrada do cliente sem normalizar. Um `../` escapa do prefixo `relatorios/`.

**Prova.**
```bash
curl -s -G localhost:3000/v1/reports/conciliacao \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode 'arquivo=../../../../etc/passwd'
# "download_url": "https://arara-conciliacao.s3.amazonaws.com/relatorios/../../../../etc/passwd"
```

**Impacto na Arara.** Sendo honesto sobre o alcance: hoje o endpoint só **monta e devolve** a URL — não lê o arquivo. Mas a URL já aponta para fora da pasta de relatórios do bucket. Dependendo de como o S3 (ou o proxy/CDN na frente) trata o `../`, vira leitura de objetos de outros lojistas (conciliações, dumps, chaves) — dado financeiro de terceiros vazando. O link ainda é apresentado como "assinado", mas não expira e não tem dono.

**Conserto.** Não aceitar caminho do cliente. Receber um id de relatório, validar contra allowlist (`^[A-Za-z0-9_-]{1,64}$`) e montar a chave no servidor, escopada ao `sub` do token. Rejeitar entrada com separador de caminho ou `..`. URL pré‑assinada de verdade (expira e escopada ao lojista).

### 9. Aviso ao lojista desligável pelo chamador · Média
**Onde:** `merchants.controller.ts`, linha 44, `if (body.notify !== false)`.

**O que é.** Quem chama a troca de payout decide se o lojista é avisado, mandando `notify:false`.

**Impacto na Arara.** É o que torna o ataque do #1 silencioso: o fraudador troca a conta, desliga o aviso, e o lojista só descobre quando o dinheiro não cai. Reduz a janela de detecção a praticamente zero.

**Conserto.** Notificação de mudança de dado sensível é decisão da plataforma. Remover o `notify` da API e sempre avisar, por canal fora da sessão (e‑mail/SMS cadastrado), com confirmação antes de efetivar.

### 10. Login sem rate limit e sem MFA · Baixa
**Onde:** `merchants.controller.ts`, `login()`, linhas 9–20.

**O que é.** Login compara e‑mail e senha sem limite de tentativas e sem segundo fator. As senhas do seed são fracas (`arara123`, `senha2024`, `mudar123`).

**Impacto na Arara.** Permite força bruta/credential stuffing. Entra como baixa porque #1 e #2 já dão acesso sem senha — mas, com a cadeia crítica corrigida, esta vira a porta de entrada.

**Conserto.** Rate limit por IP e por conta, backoff/lockout, MFA obrigatório para ações sensíveis (troca de payout). Política de senha forte e checagem contra senhas vazadas no cadastro.

### 11. Sem trilha de auditoria · Baixa
**Onde:** `merchants.controller.ts`, linhas 48–49; tabela `payout_log` (`db.ts` linhas 21–28) existe e nunca recebe `INSERT` (confirmado por busca no fonte).

**O que é.** A `payout_log` (quem alterou, conta antiga, conta nova, quando) está no schema e nunca é escrita. Toda troca de payout acontece sem rastro.

**Impacto na Arara.** Não é explorável sozinha, mas é a razão de não conseguir responder "alguém já usou essa falha?". Sem log, a investigação depende de fontes de fora do app.

**Conserto.** Gravar na `payout_log` toda alteração: `sub` do token, conta antiga e nova, quando, IP/origem. Append‑only, com alerta para mudança de payout.

---

### Observações adicionais (menores)

Itens reais, de severidade baixa, que não mudam o ranking, mas que eu registraria num report de verdade por completude:

- **M1 — Falha de assinatura retorna HTTP 500, não 401.** Token com assinatura inválida faz `jwt.verify` lançar e a exceção não é tratada → NestJS responde `500 Internal Server Error` (ver #4, contraprova). Importa por dois motivos: atrapalha monitoração (um 401 é esperado; 500 em massa vira alarme errado ou se perde no ruído) e, dependendo da config, 500 pode vazar stack trace. Conserto: capturar erro de auth e padronizar 401 (guard/exception filter).
- **M2 — Enumeração de `merchant_id` por 404 × 200.** `GET /v1/merchants/:id` responde 404 para id inexistente e 200 para existente, o que mapeia quais ids existem mesmo antes de ler dados. O enforce de dono (#3) fecha isso; de modo geral, não diferenciar "não existe" de "não autorizado".
- **M3 — Nome do bucket S3 exposto na resposta** (`arara-conciliacao.s3.amazonaws.com`). Vaza nomenclatura de infra, útil para tentativa de acesso direto/enumeração de bucket. Conserto: URL pré‑assinada opaca, sem revelar estrutura interna.
- **M4 — Comparação de senha não constante no tempo** (`m.senha !== body.senha`). Além do texto plano (#3), vaza por timing. Marginal sobre HTTP, mas some de graça com `bcrypt.compare`, que o conserto já adota.

---

## Pergunta de julgamento

> Uma das falhas deixa trocar a conta de recebimento de qualquer lojista. Você corrige o código hoje. Como você descobre se alguém já usou isso antes de você chegar, e o que você faz com o dinheiro que já saiu?

O código não guarda trilha nenhuma — a `payout_log` existe e nunca foi escrita — então não dá para confiar só no banco da aplicação; o estado atual mostra a conta de agora, não quem a trocou nem quando. A reconstrução vem de fontes independentes, cruzadas numa linha do tempo. Primeiro, backups e binlog/WAL do banco: comparando snapshots ao longo do tempo eu encontro toda troca de payout e a data dela. Depois, os logs de aplicação e do balanceador/WAF para as chamadas em `POST /merchants/payout-account` — e aqui o próprio log vazado ironicamente ajuda — cruzando a identidade autenticada (o `sub` do token) com o `merchant_id` do corpo: toda requisição em que `sub ≠ merchant_id`, ou que veio com token `alg:none`, é um forte candidato a abuso. Somo a isso os registros do rail bancário/adquirente sobre para onde o dinheiro de fato foi, comparados com a conta que cada lojista originalmente cadastrou, e os chamados de suporte reclamando de repasse que não caiu. O período anterior ao que os logs cobrem eu trato como presumidamente comprometido e confirmo com cada lojista, um a um, que a conta de payout atual é mesmo dele.

Com o dinheiro, separo conter de recuperar. Contenção primeiro: congelo os repasses para qualquer conta alterada na janela suspeita e só libero depois de reconfirmar a titularidade fora da sessão. Para o que já saiu, aciono o banco/adquirente para tentar reversão/recall das transferências mais recentes — quanto mais fresco, mais recuperável — registro boletim de fraude e preservo evidências. Em paralelo, indenizo os lojistas afetados conforme contrato e regulação em vez de esperar a recuperação, porque a falha foi de controle da plataforma, não deles; depois persigo o dinheiro nas contas‑laranja que receberam, via banco e via polícia. Envolvo jurídico e compliance desde o começo e, como houve exposição de dado pessoal pelo vazamento de cadastro, trato os deveres de notificação de incidente sob a LGPD. A parte honesta: uma vez que o valor cai numa conta‑laranja e é sacado, recuperação integral é improvável — então o objetivo real é conter rápido, deixar o lojista inteiro e fechar o buraco (confirmação fora de banda para troca de payout, para não precisar desse mutirão de novo).

---

## Mapa de evidências

Transcrição completa e reproduzível em `evidencias/evidencias-terminal.txt` (gerada contra a instância em execução). Os screenshots da pasta `shots/` são a mesma execução; cada um casa com um bloco de prova:

| Arquivo | Prova | Evidência no transcript |
|---|---|---|
| `01_login_jwt.png` | Payload do token sem `exp` (#5) | E0 |
| `02_algnone.png` | Forja `alg:none` lendo cadastro sem segredo (#2) | E2 |
| `03_idor_read.png` | Token do m_4821 lendo cadastro do m_5117 (#3) | E6 |
| `04_bola_payout.png` | Troca de payout de outro lojista — antes/depois (#1) | E1 |
| `05_chain_unauth.png` | `alg:none` + BOLA sem nenhuma credencial (#1+#2) | E3 |
| `06_mass_enum.png` | Dump de senha/`api_key`/`webhook_secret` de todos (#3/#6) | E6 |
| `07_hardcoded_secret.png` | Token assinado com `arara-2024` aceito (#4) | E4 |
| `08_expired.png` | Token vencido aceito (#5) | E5 |
| `09_path_traversal.png` | `../` escapando do prefixo de relatórios (#8) | E7 |
| `10_token_in_log.png` | Bearer inteiro gravado no log (#7) | E8 |

---

## Código corrigido (o "depois")

Arquivos completos em `corrigido/`. Os pontos centrais:

### `auth.ts` — mata `alg:none`, segredo no ambiente, expiração
```ts
const JWT_SECRET = process.env.JWT_SECRET;
if (!JWT_SECRET || JWT_SECRET.length < 32) {
  throw new Error('JWT_SECRET ausente ou fraco'); // nao sobe inseguro (#4)
}

export function assinarToken(merchantId: string): string {
  return jwt.sign({ sub: merchantId }, JWT_SECRET, {
    algorithm: 'HS256', expiresIn: '15m',          // expira (#5)
  });
}

export function lerToken(authorization?: string): { sub: string } {
  const token = (authorization || '').replace(/^Bearer\s+/i, '').trim();
  if (!token) throw new UnauthorizedException('token ausente');
  // sem leitura de header, sem ramo 'none': algoritmo travado (#2), exp volta a valer (#5)
  return jwt.verify(token, JWT_SECRET, { algorithms: ['HS256'] }) as { sub: string };
}
```

### `merchants.controller.ts` — dono vem do token, DTO sem segredos, auditoria
```ts
// troca de payout
const merchantId = claims.sub;                       // alvo vem do token (#1)
if (body.merchant_id && body.merchant_id !== merchantId)
  throw new ForbiddenException('nao autorizado a alterar outro lojista');
if (!body.step_up_ok)                                 // 2FA p/ dado financeiro (#1)
  throw new ForbiddenException('confirmacao de segundo fator obrigatoria');

// ... UPDATE ...
db.prepare(`INSERT INTO payout_log
  (merchant_id, quando, conta_antiga, conta_nova, alterado_por)
  VALUES (?,?,?,?,?)`).run(merchantId, new Date().toISOString(),
    contaAntiga, contaNova, claims.sub);              // auditoria (#11)

// resposta via DTO, sem senha/api_key/webhook_secret (#3)
// GET /:id -> if (claims.sub !== id) throw ForbiddenException  (#1/#3)
// login -> bcrypt.compare + rate limit/lockout (#3/#10/M4)
```

### `reports.controller.ts` — sem log de token, sem traversal
```ts
const ref = String(q.ref ?? '');
if (!/^[A-Za-z0-9_-]{1,64}$/.test(ref))
  throw new BadRequestException('referencia invalida'); // barra '/' e '..' (#8)
const chave = `relatorios/${claims.sub}/${ref}.csv`;    // escopado ao dono
// nao logar Authorization nem params crus (#7); URL pré-assinada que expira (#8)
```

---

## Validação das correções — antes × depois

Correções aplicadas num lab paralelo (porta 3001, segredo via ambiente); mesmos ataques rodados de novo.

| Ataque | Antes | Depois |
|---|---|---|
| Forja `alg:none` | 200 OK | 401 |
| Trocar payout de outro (BOLA) | 201 | 403 |
| Token forjado/expirado | 200 OK | 401 |
| Ler cadastro de outro (IDOR) | 200 OK | 403 |
| Token com segredo `arara-2024` | 200 OK | 401 |
| Path traversal | URL fora da pasta | 400 |
| Trocar a **própria** conta (happy path) | 201 | 201 (segue funcionando) |

Prints do "depois" em `shots/after/`. Código que rodou essa validação em `corrigido-rodando/`.

---

## Declaração de uso de IA

O enunciado pede isto e é explícito: "declare o que foi você e o que foi a máquina. Usar não tira ponto. Mentir tira." Então, honestamente:

- **IA:** apoio na leitura dos cinco arquivos e no levantamento dos pontos suspeitos; subida do lab local; escrita e execução dos comandos de prova (`curl` e geradores de token forjado); captura das saídas; redação da primeira versão do texto; e um segundo passo de validação que subiu o lab de novo e reexecutou todos os PoCs contra a instância viva para confirmar que cada saída colada é real.
- **Humano (eu):** revisão de cada achado, da severidade, do ranking e do impacto de negócio; conferência de que cada PoC bate com o que está escrito; decisão sobre o que entra e o que fica de fora; ajuste do texto e das recomendações de conserto para o contexto da Arara. Entendo e sei defender cada item daqui.

As falhas no fonte estão marcadas com `[plantado]` pelos autores do lab; usei isso para conferir a cobertura, não como atalho — cada uma está provada contra a instância em execução.
