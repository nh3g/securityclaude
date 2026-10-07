# Relatório de segurança: Arara Pay (lab)

**Candidato:** Enzo Augusto Ferreira
**Data:** 07/10/2026
**Escopo:** cinco arquivos em `src/` (`auth.ts`, `db.ts`, `merchants.controller.ts`, `reports.controller.ts`, `main.ts`). Todas as provas foram executadas contra a instância local em `http://localhost:3000`, com banco em memória e sem nenhum sistema real envolvido.

---

## Resumo executivo

A API tem uma cadeia de falhas que termina em dinheiro saindo. A verificação de token aceita `alg:none`, então qualquer pessoa consegue forjar a identidade de qualquer lojista sem ter conta nem senha. E o endpoint que troca a conta de recebimento (payout) decide de quem é a conta olhando o corpo da requisição, e não o token. Juntas, as duas falhas permitem redirecionar o recebimento de qualquer lojista para a conta do fraudador, com o aviso por e-mail desligado na mesma chamada e sem nenhum registro de quem fez a troca.

Em paralelo, qualquer token lê o cadastro completo de qualquer lojista, com senha em texto plano, `api_key` e `webhook_secret` (que, para piorar, é o mesmo para todos). A primeira coisa a corrigir é a autorização da troca de payout junto com a verificação do JWT, no mesmo deploy. Uma sem a outra deixa o caminho crítico aberto.

---

## Metodologia e ambiente

Li os cinco arquivos para levantar os pontos suspeitos, subi o lab (`npm install && npm start`, Node 22) e rodei cada ataque com `curl`, confirmando o efeito no estado da aplicação. Na prática isso quis dizer ler o cadastro antes e depois da requisição e conferir o log do servidor. Os tokens forjados (`alg:none`, HS256 assinado com o segredo do código e um token já expirado) foram gerados com um script pequeno de HMAC, sem biblioteca externa, para a prova ficar auditável. As saídas coladas e os screenshots são da mesma execução. A transcrição completa está em `evidencias/evidencias-terminal.txt`.

---

## Ranking de correção

O critério foi peso maior para dinheiro saindo agora, depois a facilidade de exploração (precisa de credencial ou não) e o alcance (quantos lojistas pega). Falha que só fica grave quando combinada com outra herda a urgência da cadeia.

| # | Falha | Severidade | Por que nessa posição |
|---|---|---|---|
| 1 | Troca de payout sem checar dono (BOLA) | Crítica | É a ação que move dinheiro. Um campo no corpo decide a vítima. |
| 2 | JWT aceita `alg:none` | Crítica | Transforma a #1 em ataque sem conta nenhuma. Vai junto da #1. |
| 3 | Vazamento do cadastro e senha em texto plano | Crítica | Entrega senha, `api_key` e `webhook_secret` de todos. Takeover em massa. |
| 4 | Segredo do JWT fixo no código | Alta | Caminho de forja que independe do `alg:none`. Exige rotacionar segredo. |
| 5 | Token sem expiração e `ignoreExpiration` | Alta | Qualquer token vazado vale para sempre. |
| 6 | `webhook_secret` igual para todos | Alta | Permite forjar "pagamento aprovado" de outro lojista. |
| 7 | Token e parâmetros em log (debug para CloudWatch) | Média | Canal de vazamento que alimenta a #3 e a #5. |
| 8 | Path traversal no relatório | Média | Entrada do cliente monta o caminho do arquivo sem normalizar. |
| 9 | Aviso ao lojista desligável pelo chamador | Média | Deixa a fraude silenciosa. Agrava a #1. |
| 10 | Login sem rate limit e sem MFA | Baixa | Força bruta de senha fraca. Não é o caminho mais curto aqui. |
| 11 | Sem trilha de auditoria (`payout_log` nunca escrito) | Baixa | Não é explorável sozinha, mas impede responder "alguém já usou isso?". |

As observações menores (M1 a M4) estão no fim da seção de achados e não mudam o ranking.

---

## Achados

### 1. Troca de payout sem validar titularidade (BOLA) · Crítica
**Onde:** `merchants.controller.ts`, `trocarPayout()`, linhas 22 a 53.

**O que é.** O endpoint `POST /v1/merchants/payout-account` pega o `merchant_id` do corpo da requisição (linha 28) e atualiza a conta de recebimento daquele id. Em nenhum momento ele confere se o token pertence ao lojista que está sendo alterado. Na prática, qualquer chamador autenticado troca a conta de qualquer lojista.

**A prova.** O atacante é o `m_4821`, com login legítimo. O alvo é o `m_0093`, que tem R$ 48.200,00 de saldo.

```bash
# conta de payout do m_0093 antes:  237 / 0001 / 12345-6 / 11222333000181

curl -s -i -X POST localhost:3000/v1/merchants/payout-account \
  -H "Authorization: Bearer $TOKEN_m4821" \
  -d '{"merchant_id":"m_0093","banco":"999","agencia":"6666",
       "conta":"00000-0","cpf_cnpj":"00000000000000","notify":false}'
# HTTP/1.1 201 Created

# conta de payout do m_0093 depois: 999 / 6666 / 00000-0 / 00000000000000  (persistido)
```

Vale guardar para a defesa: o corpo da resposta devolve o registro do lojista como ele estava antes do `UPDATE`, porque o objeto é lido antes da escrita. Por isso a prova confirma a troca relendo o cadastro depois, e não pela resposta do POST.

**O impacto na Arara.** É o pior tipo de falha para um gateway, porque o dinheiro do lojista cai na conta do fraudador. Com um laço sobre os ids, o atacante reescreve o payout da base inteira antes do próximo ciclo de liquidação e desvia tudo que seria repassado. Nos três lojistas do lab isso dá R$ 163.000 em saldo; em produção é o volume de cada lojista por ciclo. O prejuízo bate na Arara duas vezes, porque ela perde o dinheiro e ainda indeniza o lojista lesado, já que a falha é de controle da plataforma.

**O conserto.** O id a ser alterado tem que vir do token (`claims.sub`), nunca do corpo. Se um dia existir uma conta-mãe operando sub-lojistas, aí se valida explicitamente que o `claims.sub` tem permissão sobre aquele `merchant_id`, em vez de confiar no campo. Isso não quebra integrador, porque o chamador legítimo só mexe na própria conta e para ele o `merchant_id` já é igual ao `sub`, então exigir essa igualdade é compatível com o contrato atual. Dá para fazer em duas fases, primeiro só registrando e alertando quando o `sub` e o `merchant_id` divergem, e depois bloqueando. Por cima disso, eu pediria 2FA para mudar payout e gravaria a alteração na `payout_log`.

### 2. Verificação do JWT aceita `alg:none` · Crítica
**Onde:** `auth.ts`, `lerToken()`, linhas 14 a 26.

**O que é.** A função lê o cabeçalho do token para decidir como vai verificar. Quando o atacante manda `alg:none`, o código pula a assinatura e aceita o payload como verdade (linhas 21 a 26). É o próprio atacante quem escolhe não ter a assinatura checada. Com isso dá para forjar token para qualquer `sub` sem conhecer segredo nenhum.

**A prova.**
```bash
# token forjado: header {"alg":"none","typ":"JWT"}, payload {"sub":"m_0093"}, sem assinatura
# eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJtXzAwOTMifQ.

curl -s localhost:3000/v1/merchants/m_0093 -H "Authorization: Bearer $TOKEN_NONE"
# { "id":"m_0093", "senha":"arara123", "api_key":"sk_live_m0093_8f2a1c",
#   "webhook_secret":"whsec_plataforma_unico", ... }   -> 200 OK
```

Encadeando com a #1, a troca de payout acontece sem nenhuma credencial. Basta um token forjado com `sub` qualquer:
```bash
curl -s -X POST localhost:3000/v1/merchants/payout-account \
  -H "Authorization: Bearer $TOKEN_NONE_ANONIMO" \
  -d '{"merchant_id":"m_5117","banco":"001","agencia":"0001","conta":"13337-0", ...}'
# HTTP 201  ->  m_5117 passa a ter a conta 13337-0
```

**O impacto na Arara.** Sozinha, já é bypass total de autenticação. Combinada com a #1, o atacante nem precisa de uma conta de lojista para desviar o recebimento de todo mundo. É o que leva a #1 de "qualquer lojista cadastrado" para "qualquer pessoa na internet".

**O conserto.** A regra é nunca deixar o token dizer como ele deve ser verificado. Tiro a leitura manual do cabeçalho e o ramo `alg:none`, e chamo `jwt.verify` com a lista de algoritmos travada em `['HS256']`. A própria lib rejeita o resto, inclusive `none`. Não quebra integrador, porque token de verdade é HS256 e continua valendo.

### 3. Cadastro completo exposto e senha em texto plano · Crítica
**Onde:** `merchants.controller.ts`, `consultar()` linhas 55 a 63 e resposta de `trocarPayout` (linha 52); `db.ts`, coluna `senha` em texto plano e comparação `m.senha !== body.senha`.

**O que é.** O `GET /v1/merchants/:id` devolve a linha inteira do lojista para qualquer token, sem conferir dono, e isso inclui `senha`, `api_key` e `webhook_secret`. A senha está guardada em texto plano.

**A prova.** Enumeração da base inteira com um único token legítimo:
```
m_0093 | senha=arara123  | api_key=sk_live_m0093_8f2a1c | whsec=whsec_plataforma_unico
m_4821 | senha=senha2024 | api_key=sk_live_m4821_3b9e7d | whsec=whsec_plataforma_unico
m_5117 | senha=mudar123  | api_key=sk_live_m5117_c1d4f0 | whsec=whsec_plataforma_unico
```

**O impacto na Arara.** Com um único token, ou com um `alg:none` da #2, o atacante varre a base e coleta senha, chave de API e segredo de webhook de todo mundo. Como a senha está em texto plano, quem lê o banco, um dump ou um backup já sai com as credenciais na mão, sem precisar quebrar hash. Se o lojista reusa senha, o estrago passa da Arara. É credencial e dado de cliente vazando em massa, com todo o peso de LGPD.

**O conserto.** A API passa a devolver só o que o cliente precisa (um DTO com id, nome, e-mail, payout mascarado e saldo) e nunca senha, `api_key` ou `webhook_secret`. Coloco a checagem de dono no `GET /:id`, igual à #1. Senha vai para hash forte (bcrypt ou argon2), com migração sem logout, regravando com hash no próximo login feito com a senha antiga. Rotaciono as `api_key`s e os `webhook_secret`s já expostos. Se algum integrador faz parse do corpo inteiro, versiono o endpoint numa v2.

### 4. Segredo do JWT fixo no código · Alta
**Onde:** `auth.ts`, linha 4, `JWT_SECRET = 'arara-2024'`.

**O que é.** O segredo que assina os tokens está escrito no fonte. Quem tiver o repositório, ou um vazamento dele, assina tokens HS256 válidos para qualquer lojista. É um caminho de forja que independe do `alg:none`. E tem o agravante de o segredo ser fraco, já que `arara-2024` é adivinhável até sem acesso ao código.

**A prova.**
```bash
# token HS256 assinado pelo atacante com o segredo 'arara-2024' do código
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  localhost:3000/v1/merchants/m_5117 -H "Authorization: Bearer $HS256_arara2024"
# HTTP 200  (aceito como legítimo)

# contraprova: mesma estrutura, assinada com segredo errado -> HTTP 500 (rejeitado; ver M1)
```

**O impacto na Arara.** Qualquer pessoa com o segredo (repo, histórico de git, pipeline de CI, log) emite tokens de qualquer lojista por tempo indeterminado. Encadeado com a #1 e a #3, isso vira desvio de dinheiro e coleta de credenciais.

**O conserto.** O segredo sai do código e vai para um cofre ou variável de ambiente, com valor forte e aleatório de pelo menos 32 bytes. A rotação usa um identificador de chave (`kid`) e uma janela em que a chave antiga e a nova valem ao mesmo tempo, para não deslogar todo mundo de uma vez. Integração servidor a servidor usa `api_key`, não JWT.

### 5. Token sem expiração e `ignoreExpiration` ligado · Alta
**Onde:** `auth.ts`, `assinarToken()` linha 8 e `lerToken()` linha 31.

**O que é.** O token é assinado sem `exp`, e a verificação ainda passa `ignoreExpiration:true`. O resultado é que o token não expira nunca, e mesmo um token com `exp` no passado é aceito.

**A prova.**
```bash
# payload do token legítimo: não existe campo exp
# {"sub":"m_4821","iat":1791397791}

# token com exp lá em 2023 é aceito do mesmo jeito:
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  localhost:3000/v1/merchants/m_5117 -H "Authorization: Bearer $TOKEN_EXPIRADO"
# HTTP 200  (deveria ser 401)
```

**O impacto na Arara.** Qualquer token que vaze uma vez (ver #7) vale para sempre. Não existe janela que feche sozinha, nem jeito de deixar o token velho morrer. Revogação vira um problema manual que o sistema hoje não resolve.

**O conserto.** Token de acesso curto, na casa de 15 minutos, com `exp`, e fora o `ignoreExpiration`. Para manter sessão longa, um refresh token revogável. Vale um período de transição avisando os backends para passarem a usar `api_key`.

### 6. `webhook_secret` igual para todos os lojistas · Alta
**Onde:** `db.ts`, `seed()`. O `whsec_plataforma_unico` aparece nos três lojistas.

**O que é.** Todo lojista compartilha o mesmo segredo de webhook. Como ele ainda vaza pela resposta da API (#3), qualquer um que leu um cadastro consegue assinar webhooks como se fosse a plataforma, inclusive para outro lojista.

**O impacto na Arara.** O webhook é o que avisa o lojista que "o pagamento foi aprovado". Com segredo único, o fraudador forja essa notificação para o sistema de um lojista e dispara a entrega de um produto por uma venda que nunca foi paga. É prejuízo direto para o lojista e disputa ou chargeback contra a Arara.

**O conserto.** Segredo único por lojista, aleatório, guardado cifrado e nunca devolvido pela API depois de criado. Cada webhook é assinado e verificado com o segredo daquele lojista. Rotação com janela aceitando o antigo e o novo.

### 7. Token e parâmetros caindo no log (debug para CloudWatch) · Média
**Onde:** `reports.controller.ts`, linha 15.

**O que é.** O endpoint de conciliação loga o header `Authorization` inteiro e todos os parâmetros, num nível debug que vai parar no CloudWatch.

**A prova.** Linha real do log do servidor após uma requisição autenticada:
```
DEBUG [reports] conciliacao auth=Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJtXzQ4MjEi...4Z1P params={"arquivo":"out.csv"}
```

**O impacto na Arara.** O token inteiro fica guardado no log. Quem tem acesso ao CloudWatch (um time interno grande, um integrador de observabilidade, ou um vazamento de logs) replica a sessão. E como o token não expira (#5), cada linha de log é uma credencial permanente.

**O conserto.** Nunca logar o header de autorização nem o corpo ou os parâmetros crus. No máximo, registro o `sub` já verificado e um id de requisição. Baixo o nível do log, coloco redação de segredos no pipeline e restrinjo o acesso e a retenção no CloudWatch. Os tokens que já foram parar no log precisam ser rotacionados.

### 8. Path traversal no relatório de conciliação · Média
**Onde:** `reports.controller.ts`, linha 18, `` `relatorios/${q.arquivo}` ``.

**O que é.** O caminho do arquivo é montado concatenando a entrada do cliente sem normalizar nada. Um `../` escapa do prefixo `relatorios/`.

**A prova.**
```bash
curl -s -G localhost:3000/v1/reports/conciliacao \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode 'arquivo=../../../../etc/passwd'
# "download_url": "https://arara-conciliacao.s3.amazonaws.com/relatorios/../../../../etc/passwd"
```

**O impacto na Arara.** Sendo honesto sobre o alcance, hoje o endpoint só monta e devolve a URL, não lê o arquivo. Mas a URL já aponta para fora da pasta de relatórios. Dependendo de como o S3, ou um proxy ou CDN na frente, trata o `../`, isso vira leitura de objetos de outros lojistas (conciliações, dumps, chaves), ou seja, dado financeiro de terceiros vazando. O link ainda é apresentado como "assinado", mas não expira e não tem dono.

**O conserto.** Não aceitar caminho vindo do cliente. Recebo um id de relatório, valido contra uma allowlist (`^[A-Za-z0-9_-]{1,64}$`) e monto a chave no servidor, escopada ao `sub` do token. Qualquer entrada com separador de caminho ou `..` é rejeitada. E uso URL pré-assinada de verdade, que expira e é escopada ao lojista.

### 9. Aviso ao lojista desligável pelo chamador · Média
**Onde:** `merchants.controller.ts`, linha 44, `if (body.notify !== false)`.

**O que é.** Quem chama a troca de payout é quem decide se o lojista vai ser avisado, mandando `notify:false`.

**O impacto na Arara.** É isso que deixa o ataque da #1 silencioso. O fraudador troca a conta, desliga o aviso, e o lojista só percebe quando o dinheiro não cai. A janela de detecção vai praticamente a zero.

**O conserto.** Notificar mudança de dado sensível é decisão da plataforma, não do chamador. Tiro o `notify` da API e aviso sempre, por um canal fora da sessão (e-mail ou SMS cadastrado), com confirmação antes de efetivar.

### 10. Login sem rate limit e sem MFA · Baixa
**Onde:** `merchants.controller.ts`, `login()`, linhas 9 a 20.

**O que é.** O login compara e-mail e senha sem limite de tentativas e sem segundo fator. As senhas do seed são fracas (`arara123`, `senha2024`, `mudar123`).

**O impacto na Arara.** Dá para fazer força bruta e credential stuffing. Entra como baixa porque a #1 e a #2 já dão acesso sem senha, mas no dia em que a cadeia crítica estiver corrigida é por aqui que o atacante volta a entrar.

**O conserto.** Rate limit por IP e por conta, backoff e lockout progressivo, e MFA obrigatório para ações sensíveis como a troca de payout. Política de senha forte e checagem contra senhas já vazadas no momento do cadastro.

### 11. Sem trilha de auditoria · Baixa
**Onde:** `merchants.controller.ts`, linhas 48 a 49. A tabela `payout_log` (`db.ts`, linhas 21 a 28) existe e nunca recebe um `INSERT`, o que confirmei buscando no fonte.

**O que é.** A `payout_log`, que teria quem alterou, a conta antiga, a conta nova e quando, está no schema e nunca é escrita. Toda troca de payout acontece sem deixar rastro.

**O impacto na Arara.** Sozinha não é explorável, mas é exatamente o motivo de não conseguir responder "alguém já usou essa falha?". Sem log, a investigação depende de fontes de fora da aplicação.

**O conserto.** Gravar na `payout_log` toda alteração: o `sub` do token, a conta antiga, a conta nova, quando e de qual origem ou IP. Append-only, com alerta disparado em mudança de payout.

---

### Observações adicionais (menores)

Fora os onze, anotei quatro coisas menores, de severidade baixa, que não mudam o ranking mas que eu colocaria num report de verdade por completude.

**M1.** Um token com assinatura inválida faz o `jwt.verify` lançar, e a exceção não é tratada, então o NestJS responde `500 Internal Server Error` em vez de `401`. Importa por dois motivos. Atrapalha a monitoração, já que um 401 é esperado mas 500 em massa ou vira alarme errado ou some no ruído, e, dependendo da configuração, um 500 pode vazar stack trace. O conserto é capturar o erro de auth e padronizar o 401.

**M2.** O `GET /v1/merchants/:id` responde 404 para id inexistente e 200 para id existente, o que já deixa mapear quais ids existem antes mesmo de ler qualquer dado. A checagem de dono da #3 fecha isso.

**M3.** A resposta expõe o nome do bucket S3 (`arara-conciliacao.s3.amazonaws.com`), vazando nomenclatura de infraestrutura que ajuda numa tentativa de acesso direto ou de enumeração de bucket. O conserto é usar URL pré-assinada opaca.

**M4.** A comparação de senha com `!==` não é constante no tempo. Além do problema do texto plano da #3, isso vaza por timing. É marginal sobre HTTP, mas desaparece de graça quando se adota `bcrypt.compare`, que o conserto já faz.

---

## Pergunta de julgamento

> Uma das falhas deixa trocar a conta de recebimento de qualquer lojista. Você corrige o código hoje. Como você descobre se alguém já usou isso antes de você chegar, e o que você faz com o dinheiro que já saiu?

O código não guarda trilha nenhuma, já que a `payout_log` existe e nunca foi escrita, então não dá para confiar só no banco da aplicação. O estado atual mostra a conta de agora, não quem a trocou nem quando. A reconstrução vem de fontes independentes, cruzadas numa linha do tempo. Começo pelos backups e pelo binlog ou WAL do banco, porque comparando snapshots ao longo do tempo eu acho toda troca de payout e a data de cada uma. Depois vou nos logs de aplicação e do balanceador ou WAF atrás das chamadas em `POST /merchants/payout-account`, e aqui o próprio log vazado ironicamente ajuda. Cruzo a identidade autenticada (o `sub` do token) com o `merchant_id` do corpo, e toda requisição em que o `sub` é diferente do `merchant_id`, ou que chegou com token `alg:none`, é forte candidata a abuso. Somo a isso os registros do rail bancário e do adquirente sobre para onde o dinheiro de fato foi, comparados com a conta que cada lojista cadastrou originalmente, e os chamados de suporte reclamando de repasse que não caiu. O período anterior ao que os logs cobrem eu trato como presumidamente comprometido, e confirmo com cada lojista, um a um, que a conta de payout atual é mesmo dele.

Com o dinheiro, separo conter de recuperar. Contenção vem primeiro. Congelo os repasses para qualquer conta alterada na janela suspeita e só libero depois de reconfirmar a titularidade fora da sessão. Para o que já saiu, aciono o banco e o adquirente para tentar reversão ou recall das transferências mais recentes, porque quanto mais fresco mais recuperável, registro boletim de fraude e preservo as evidências. Em paralelo, indenizo os lojistas afetados conforme contrato e regulação, sem esperar a recuperação, já que a falha foi de controle da plataforma e não deles. Depois persigo o dinheiro nas contas-laranja que receberam, pela via bancária e pela via policial. Jurídico e compliance entram desde o começo, e, como houve exposição de dado pessoal no vazamento de cadastro, trato os deveres de notificação de incidente sob a LGPD. A parte honesta é que, uma vez que o valor cai numa conta-laranja e é sacado, recuperação integral é improvável. Então o objetivo real é conter rápido, deixar o lojista inteiro e fechar o buraco, com confirmação fora de banda para troca de payout, para não precisar desse mutirão de novo.

---

## Código corrigido (o "depois")

Os arquivos completos estão na pasta `corrigido/`. Os pontos centrais são estes.

### `auth.ts`: mata o `alg:none`, tira o segredo do código e devolve a expiração
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

### `merchants.controller.ts`: dono vem do token, DTO sem segredos e auditoria
```ts
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

### `reports.controller.ts`: sem log de token e sem traversal
```ts
const ref = String(q.ref ?? '');
if (!/^[A-Za-z0-9_-]{1,64}$/.test(ref))
  throw new BadRequestException('referencia invalida'); // barra '/' e '..' (#8)
const chave = `relatorios/${claims.sub}/${ref}.csv`;    // escopado ao dono
// nao logar Authorization nem params crus (#7); URL pré-assinada que expira (#8)
```

---

## Validação das correções, antes e depois

Apliquei as correções num lab paralelo (porta 3001, segredo via ambiente) e rodei os mesmos ataques de novo.

| Ataque | Antes | Depois |
|---|---|---|
| Forja `alg:none` | 200 OK | 401 |
| Trocar payout de outro (BOLA) | 201 | 403 |
| Token forjado ou expirado | 200 OK | 401 |
| Ler cadastro de outro (IDOR) | 200 OK | 403 |
| Token com segredo `arara-2024` | 200 OK | 401 |
| Path traversal | URL fora da pasta | 400 |
| Trocar a própria conta (happy path) | 201 | 201 (segue funcionando) |

Prints do "depois" na pasta `shots/after/`. Código que rodou essa validação em `corrigido-rodando/`.

---

## Declaração de uso de IA

O enunciado pede isto de forma explícita, que é declarar o que foi feito por mim e o que foi feito pela máquina, lembrando que usar não tira ponto e mentir tira. Então, de forma honesta: usei IA como apoio na leitura dos cinco arquivos e no levantamento dos pontos suspeitos, na subida do lab local, na escrita e na execução dos comandos de prova (os `curl` e os geradores de token forjado), na captura das saídas, na redação da primeira versão do texto e num passo de validação que subiu o lab de novo e reexecutou todos os PoCs contra a instância viva, para confirmar que cada saída colada é real.

O que foi meu: a revisão de cada achado, da severidade, do ranking e do impacto de negócio; a conferência de que cada PoC bate com o que está escrito; a decisão do que entra e do que fica de fora; e o ajuste do texto e das recomendações de conserto para o contexto da Arara. Entendo e sei defender cada item daqui. As falhas no fonte vêm marcadas com `[plantado]` pelos próprios autores do lab, e usei isso para conferir a cobertura, não como atalho, já que cada uma está provada contra a instância em execução.
