"""
Pipeline de criação de roteiros para YouTube - nicho empresas/administração
============================================================================

4 AGENTES:
1. Pesquisador  -> busca assuntos em alta (Google News RSS, sem chave de API)
1B. Referência  -> busca os vídeos mais vistos de canais de referência do
    nicho (Elementar, Primo Rico, Nerds de Negócios) via API do YouTube, e
    gera temas novos inspirados no padrão deles
2. Roteirista   -> escreve o roteiro (LLM local via Ollama)
3. Crítico      -> avalia e reprova/aprova, devolvendo feedback pro roteirista
4. Editor       -> lê o roteiro aprovado e já BUSCA os b-rolls reais no Pexels
5. Metadados    -> gera título, thumbnail detalhada, descrição e tags
6. Prompt de imagem -> transforma a expressão pedida na thumbnail num prompt
   pronto pra colar no Gemini junto com sua foto base
7. Narração      -> gera o áudio final via ElevenLabs, com pausas naturais
   entre parágrafos (não é grátis - precisa de ELEVENLABS_API_KEY e
   ELEVENLABS_VOICE_ID no .env; sem isso, só pula essa etapa)

CUSTO: R$ 0,00 nos agentes 1 a 6 (nuvem Groq ou local Ollama, ambos grátis).
Busca de b-roll (Pexels) e YouTube Data API são grátis mas sempre usam
internet. O agente 7 (ElevenLabs) É PAGO por caractere depois da cota de
teste - é o único custo real do pipeline.

QUAL IA USAR - controlado pela variável USAR_NUVEM no topo do código:

USAR_NUVEM = True (padrão, recomendado):
    Usa Groq - modelos muito mais fortes, rodando em hardware dedicado
    (rápido), com cota diária gratuita generosa. Recomendado depois de
    testar que modelo local pequeno (7B) tem limite real de capacidade
    pra esse tipo de tarefa (roteiro saindo curto mesmo com instrução
    clara, crítico repetindo reprovação genérica sem avaliar o conteúdo
    de verdade).
    1. console.groq.com/keys -> criar conta -> gerar chave (sem cartão)
    2. Coloque no .env: GROQ_API_KEY=sua_chave
    3. O código já tenta uma LISTA de modelos gratuitos em ordem
       (MODELOS_GROQ_FALLBACK, no topo do código) e usa o primeiro que
       funcionar - se um for descontinuado, ele pula pro próximo sozinho.
       Só mexa nessa lista se todos os modelos dela pararem de funcionar
       (confira os atuais em console.groq.com/dashboard/limits).

USAR_NUVEM = False:
    Volta pro Ollama 100% local e offline (testado em Ryzen 5500 + RTX
    3050 6GB, roda bem modelos de 7-8B em Q4).
    1. Instale o Ollama: https://ollama.com/download
    2. Baixe um modelo (escolha um, no terminal):
         ollama pull qwen2.5:7b-instruct     # recomendado - bom em PT-BR
         ollama pull llama3.1:8b             # alternativa sólida
    3. O Ollama já sobe um servidor local em http://localhost:11434
       (não precisa de chave de API, não precisa estar rodando o app aberto)

APIs usadas:
- Pexels (banco de vídeo gratuito) -> https://www.pexels.com/api/  (grátis, sem cartão)

INSTALAÇÃO:
    pip install openai requests python-dotenv feedparser

CONFIGURAÇÃO (.env na mesma pasta - use o .env.example como modelo):
    NUNCA escreva chave direto no código: este arquivo circula em backup,
    print e upload, e a chave vai junto. Tudo é lido do .env, que está no
    .gitignore.

    GROQ_API_KEY=sua_chave_aqui       (necessária se USAR_NUVEM = True)
    PEXELS_API_KEY=sua_chave_aqui
    YOUTUBE_API_KEY=sua_chave_aqui   (opcional - só pro agente de referência)

YOUTUBE_API_KEY (gratuita):
    1. Crie um projeto em https://console.cloud.google.com
    2. Ative a "YouTube Data API v3" pro projeto (busque no menu de APIs)
    3. Crie uma credencial do tipo "Chave de API"
    O uso normal desse pipeline fica bem dentro da cota diária gratuita
    (10.000 unidades/dia - cada canal analisado consome poucas dezenas).
    Se o Google pedir pra vincular uma conta de faturamento pra ativar a
    API, isso é só verificação de identidade - dentro da cota gratuita
    você não é cobrado.
"""

import os
import re
import json
import unicodedata
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
import requests

# Pasta onde o arquivo .py está - definida ANTES de carregar o .env, pra
# garantir que ele procura no lugar certo independente de onde o comando
# "python pipeline_canal_youtube.py" foi rodado (o diretório do terminal
# pode ser outro - é exatamente isso que causa ".env não funciona").
PASTA_DO_SCRIPT = Path(__file__).resolve().parent
CAMINHO_ENV = PASTA_DO_SCRIPT / ".env"
load_dotenv(dotenv_path=CAMINHO_ENV)

if CAMINHO_ENV.exists():
    print(f"(.env encontrado em {CAMINHO_ENV})")
else:
    print(
        f"(.env NÃO encontrado em {CAMINHO_ENV} - copie o .env.example pra "
        ".env e preencha as chaves; sem isso as etapas que usam API são puladas)"
    )

# =========================================================================
# QUAL IA USAR: local (Ollama) ou nuvem (Groq)
# =========================================================================
# Depois de testar bastante, o modelo local de 7B mostrou limite real de
# capacidade pra esse tipo de tarefa (roteiro saindo curto mesmo com
# instrução clara de tamanho, crítico repetindo a mesma reprovação genérica
# sem realmente avaliar o conteúdo). Groq roda modelos muito mais fortes em
# hardware dedicado (rápido) e também tem cota diária gratuita generosa.
#
# COMO CONSEGUIR A CHAVE GRÁTIS DO GROQ:
#   1. console.groq.com/keys -> criar conta -> gerar chave (sem cartão)
#   2. Coloque no .env: GROQ_API_KEY=sua_chave
#   3. Confira o nome exato de um modelo gratuito atual em
#      console.groq.com/dashboard/limits (a lista muda com frequência)

USAR_NUVEM = True  # True = usa Groq | False = volta pro Ollama 100% local

GROQ_KEY = os.getenv("GROQ_API_KEY", "")
# ATENÇÃO: o Groq descontinua/muda modelos gratuitos com muita frequência -
# já tentei fixar um nome único 3 vezes nessa conversa e todos pararam de
# funcionar (descontinuado, cota de saída baixa demais, ou nem existe mais
# nessa conta). Em vez de depender de UM nome fixo, o código tenta cada
# modelo desta lista em ordem e usa o primeiro que funcionar - se um for
# descontinuado no futuro, o código simplesmente pula pro próximo sozinho,
# sem precisar editar nada. Ordem pensada em cota de tokens de saída/min
# (importante pra roteiro longo) e força do modelo.
MODELOS_GROQ_FALLBACK = [
    # Confirmado em console.groq.com/docs/deprecations: llama-3.3-70b-versatile,
    # qwen/qwen3-32b e llama-3.1-8b-instant foram TODOS descontinuados (jul/ago
    # 2026) - os dois abaixo são os substitutos OFICIAIS recomendados pela
    # própria Groq pra esses modelos, não um chute.
    "openai/gpt-oss-120b",  # substitui llama-3.3-70b-versatile e qwen3-32b
    "openai/gpt-oss-20b",   # substitui llama-3.1-8b-instant (mais leve/rápido)
]

# Ollama expõe uma API compatível com o formato OpenAI - só aponta o
# base_url pro servidor local. api_key pode ser qualquer texto, o Ollama
# não valida.
client_local = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
client_groq = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_KEY) if GROQ_KEY else None

# Precisa ser exatamente o nome que você baixou com "ollama pull"
MODEL = "qwen2.5:7b-instruct"

# NUNCA deixe chave escrita direto aqui: este arquivo circula (backup,
# print, upload) e a chave vai junto. Tudo vem do .env, que fica fora do
# controle de versão (veja .gitignore) - use o .env.example como modelo.
PEXELS_KEY = os.getenv("PEXELS_API_KEY", "")
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY", "")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
# Pega o voice_id em elevenlabs.io/app/voice-library (escolha uma voz ou
# use a sua clonada, se tiver) - fica no painel de detalhes da voz.
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
# Multilingual v2 é o recomendado pra narração longa em PT-BR - mais
# estável em textos longos que o v3 (que também é mais caro e limitado a
# 5.000 caracteres por chamada).
ELEVENLABS_MODEL = "eleven_multilingual_v2"

# Termos com pronúncia problemática - ADICIONE AQUI conforme for notando na
# prática (sigla, nome de marca, palavra estrangeira). O valor é como você
# quer que seja LIDO (escrito por extenso ou foneticamente em português).
# IMPORTANTE: só regra tipo "alias" (troca de texto) funciona no
# Multilingual v2 - regra de fonema IPA só funciona em turbo_v2/flash_v2,
# que não usamos aqui (por isso não tem opção de fonema abaixo). Os
# exemplos são só ponto de partida - ajuste conforme ouvir o resultado.
REGRAS_PRONUNCIA_ELEVENLABS = {
    "CEO": "sê é ó",
    "CFO": "sê éfe ó",
    "e-commerce": "i comêrs",
    "cashback": "quéchi béqui",
}
CAMINHO_CACHE_DICIONARIO = PASTA_DO_SCRIPT / ".pronuncia_dict_cache.json"

# Canais de referência do nicho pra puxar inspiração dos vídeos que mais
# renderam. Handles confirmados (conferidos por busca, não chutados):
# - Elementar: documentário narrativo de empresas/negócios (o mais próximo
#   do estilo do canal)
# - primorico: Primo Rico (Thiago Nigro), finanças/investimentos
# - NerdsdeNegocios: Peter Jordan, maior canal de empreendedorismo do Brasil
# Use o handle exatamente como aparece na URL do canal (youtube.com/@handle).
CANAIS_REFERENCIA = ["Elementar", "primorico", "NerdsdeNegocios"]


# =========================================================================
# PROMPTS (os que já validamos juntos)
# =========================================================================

ROTEIRO_PROMPT = """Você é um roteirista de vídeos de YouTube sobre empresas e administração,
estilo documentário narrativo (referência: Elementar, Primo Rico, Nerds de
Negócios). Canal faceless, narrado em primeira pessoa. Siga as instruções
abaixo na ordem exata. Não pule nenhum passo.

TEMA: {tema}

REGRAS DE ENTREGA (muito importantes - leia com atenção):
- Sua resposta final deve conter SOMENTE o roteiro no formato NARRAÇÃO:/
  VISUAL:, do início ao fim. NÃO escreva saudação, comentário sobre a
  tarefa, nem frases como "Entendido" ou "Vou revisar". NÃO repita os
  nomes dos passos (PASSO 1, BLOCO A, etc.) na resposta final - eles são
  só um guia de raciocínio pra você, não fazem parte do texto entregue.
- NÃO escreva o roteiro duas vezes. Escreva uma única vez, do início ao
  fim, e pare.
- Se o TEMA acima não citar uma empresa específica (por exemplo, for um
  tema de tendência de mercado ou setor), você MESMO precisa escolher UMA
  empresa real e específica para ser o fio condutor da história logo no
  Passo 1, e usar o NOME REAL dela em todo o roteiro - nunca deixe um
  espaço em branco ou marcador no lugar do nome da empresa. Se não tiver
  certeza absoluta de um fato sobre ela, marque só aquele fato com
  [VERIFICAR], mas o NOME da empresa nunca leva marcador.

REGRAS FIXAS (valem para todo o roteiro):
- Todo material visual sugerido tem que EXISTIR em banco de stock gratuito
  (Pexels/Envato/Storyblocks): reunião, escritório, fábrica, prateleira de
  loja, trânsito de cidade, dinheiro, gráfico em tela, mãos digitando,
  assinatura de papel, contêiner em porto. NUNCA descreva uma cena única
  e específica que não existe pronta (proibido: "o CEO olhando pela janela
  naquele dia").
- [ARQUIVO REAL] só pode aparecer sozinho numa linha VISUAL, nunca dentro
  do texto da NARRAÇÃO, nem antes nem depois da palavra "VISUAL:". Use
  [ARQUIVO REAL] quando o vídeo precisar de algo específico da empresa
  (logo, produto, fundador, prédio) que só existe em foto de imprensa/
  arquivo, não em banco de stock. Isso é uma instrução pra edição, não um
  substituto pro nome da empresa nem algo que aparece no texto narrado.
  Exemplo ERRADO (nunca faça isso): "...pagou a dívida no prazo. [ARQUIVO
  REAL] foto do contrato VISUAL: b-roll genérico de assinatura" - aqui
  [ARQUIVO REAL] está dentro da narração, isso é PROIBIDO. Exemplo CERTO:
  a linha NARRAÇÃO não menciona [ARQUIVO REAL] em hipótese nenhuma; se
  esse trecho precisa de imagem real, a linha VISUAL correspondente é só
  "VISUAL: [ARQUIVO REAL] foto do contrato de reestruturação", nada mais.
- Cada linha NARRAÇÃO leva exatamente UMA linha VISUAL depois dela, nunca
  duas marcações visuais pra mesma narração.
- PROIBIDO escrever na NARRAÇÃO qualquer palavra de instrução usada neste
  prompt: "mini-gancho", "bloco", "passo", "backstory", "miolo" nunca
  aparecem no texto narrado - são conceitos pra você aplicar, não rótulos
  pra escrever. Exemplo ERRADO (nunca faça isso): "O primeiro mini-gancho:
  a investigação revelou que..." - isso é o mesmo erro de escrever "PASSO
  1" no meio do roteiro. O mini-gancho é só o dado/revelação em si, sem
  anunciar que é um.
- REGRA DE VERIFICAÇÃO (a mais importante desta lista - leia com atenção):
  por padrão, marque [VERIFICAR] em QUALQUER número específico sobre uma
  empresa real - percentual, valor em R$/US$, quantidade de pessoas,
  contagem de itens, data exata - A MENOS que seja um fato amplamente
  conhecido e fácil de checar (ex: ano de fundação de uma empresa famosa,
  quem é o fundador). Você não tem como pesquisar fatos - então o padrão
  seguro é marcar, não confiar na própria memória. Isso vale mesmo que o
  número pareça plausível ou específico o suficiente pra parecer real -
  "parecer real" não é o mesmo que "ser verificado". Exemplo do erro real
  que já aconteceu: um roteiro sobre uma empresa citou "200 mil notas
  fiscais alteradas", "12% das transações", "R$ 1,2 bilhão em receita
  perdida", "corte de 15% da força de trabalho" e mais uma dezena de
  números parecidos - TODOS sem [VERIFICAR], todos possivelmente
  inventados. Isso é uma alegação factual falsa sobre uma empresa de
  verdade se não for checado - é o erro mais grave que este roteiro pode
  ter, mais grave que qualquer problema de ritmo ou gancho.
- PROIBIDO inventar pessoa comum: nunca crie um nome de funcionário,
  gerente, cliente ou participante de reunião que não seja uma figura
  pública real e conhecida (fundador/CEO famoso, por exemplo). Colocar
  fala ("disse que...") na boca de uma pessoa inventada é o mesmo tipo de
  erro grave que número sem [VERIFICAR] - é alegação falsa sobre uma
  pessoa que ninguém consegue checar. Se precisar ilustrar uma reação
  humana, descreva de forma genérica ("um gerente de restaurante notou
  que..."), nunca invente nome próprio pra essa pessoa.
- Explique jargão técnico (ex: "M&A", "spread bancário") só quando for
  genuinamente obscuro pra quem não é da área. NÃO explique palavra que o
  público já entende pelo contexto (não faça isso: "comitê de crise, que é
  um grupo de gestão de emergências" ou "teleconferência, que é uma
  reunião online" - ninguém precisa dessa explicação). E quando explicar,
  varie a forma - não repita a fórmula "X, que é Y" toda vez, isso soa
  robótico quando dito em sequência várias vezes no mesmo roteiro.
- Frases curtas, linguagem falada (será narrada em voz, não lida).
- PROIBIDO usar estas frases prontas: "mas o que ninguém esperava",
  "e foi aí que tudo mudou", "só que a história não termina aí",
  "só que tinha um problema".

PASSO 1 - DEFINA O ÂNGULO (escreva antes do roteiro, em até 2 frases):
Responda: qual é o ponto de vista menos óbvio sobre esse tema? Qual pergunta
vai prender a pessoa até o fim? Existe uma virada ou ironia? Se o tema não
citar uma empresa, diga aqui qual empresa real você escolheu para a
história.

PASSO 2 - ESCREVA O ROTEIRO NESTA ORDEM E NESTE TAMANHO:
IMPORTANTE: as faixas abaixo são o MÍNIMO aceitável, não a meta. Escreva
sempre perto do topo de cada faixa, nunca do fundo - roteiro curto demais
é o erro mais comum e mais fácil de evitar.

BLOCO A - INTRODUÇÃO (2 a 4 frases, 60 a 90 palavras):
Comece com um número, afirmação ou situação estranha. NÃO diga o nome da
empresa nem o final ainda. Termine a introdução com uma pergunta implícita
(o leitor deve ficar se perguntando "e aí, o que aconteceu?").

BLOCO B - BACKSTORY (280 a 350 palavras):
Explique o cenário como se a pessoa não soubesse nada do assunto. Desenvolva
o contexto com detalhe - época, mercado, os personagens envolvidos. No meio
deste bloco, insira UM dado, número ou fato curioso que funcione como
mini-gancho (exemplo do que é um mini-gancho: "e olha que isso acontecia
numa empresa que, três anos antes, quase fechou as portas").

BLOCO C - MIOLO (750 a 950 palavras):
Conte a decisão ou conflito central. Explique o raciocínio de gestão por
trás da decisão (não só o fato, o porquê) - desenvolva cada etapa da
decisão com detalhe, não resuma. Insira pelo menos TRÊS mini-ganchos ao
longo deste bloco (dado novo, revelação pequena ou pergunta), um a cada
200-250 palavras aproximadamente - não deixe tudo pro final.

BLOCO D - CONEXÃO COM O FUTURO OU CONCLUSÃO (180 a 230 palavras):
Se o assunto ainda está em andamento hoje: diga o que isso sinaliza pro
futuro do setor. Se é um caso fechado: escreva a lição de gestão central,
sem soar como frase de para-choque de caminhão. Termine com uma frase de
impacto.

PASSO 3 - FORMATO DE SAÍDA (obrigatório, siga este exemplo à risca):
Cada frase ou parágrafo do roteiro vira uma linha "NARRAÇÃO:" seguida,
numa LINHA SEPARADA (aperte Enter - nunca na mesma linha), de uma linha
"VISUAL:". Exemplo de como formatar (não copie o conteúdo, só o formato -
note que NARRAÇÃO e VISUAL são sempre duas linhas diferentes):

NARRAÇÃO: Em 2015, uma empresa quase faliu com uma dívida de bilhões.
VISUAL: b-roll genérico de gráfico de linha caindo em tela

NARRAÇÃO: Cinco anos depois, ela virava uma das maiores do setor no mundo.
VISUAL: b-roll genérico de fábrica em operação, esteira de produção

Repita este padrão (NARRAÇÃO numa linha, VISUAL na linha seguinte) do
início ao fim do roteiro, sem pular nenhuma frase e sem nunca juntar as
duas na mesma linha. Não use títulos de bloco (A, B, C, D) no texto final -
eles são só um guia pra você escrever, o resultado tem que ler como um
texto corrido narrado.

ANTES DE RESPONDER, confira: (1) cada linha tem NARRAÇÃO: e VISUAL: em
linhas SEPARADAS, nunca grudadas? (2) o nome da empresa não aparece na
introdução, mas aparece (nome real, nunca marcador) no resto do roteiro?
(3) [ARQUIVO REAL], quando usado, está SÓ na linha VISUAL, nunca dentro do
texto narrado? (4) tem pelo menos 4 mini-ganchos no total (1 no backstory
+ 3 no miolo) - E a palavra "mini-gancho" em si NÃO aparece escrita em
nenhuma linha NARRAÇÃO? (5) o roteiro inteiro soma pelo menos 1300 palavras
de narração - se estiver mais curto, VOLTE e desenvolva mais cada bloco
antes de entregar, principalmente o MIOLO? (6) você escreveu o roteiro só
UMA vez, sem comentário e sem repetir os nomes dos passos? (7) CONTE quantos
números específicos (%, R$/US$, quantidade, data exata) aparecem no
roteiro - cada um tem [VERIFICAR] do lado, exceto os que forem fato público
amplamente conhecido? Se algum número específico não tiver [VERIFICAR] e
você não tiver certeza absoluta dele, adicione agora. Se alguma resposta
for não, corrija antes de entregar.
"""

AVALIACAO_PROMPT = """Você é um editor crítico de retenção de audiência para YouTube, nicho
empresas e administração, vídeo longo (não Shorts). Avalie o roteiro abaixo
seguindo EXATAMENTE o template de resposta no final. Preencha cada campo,
não pule nenhum. Seja direto - se algo está fraco, diga que está fraco.

ROTEIRO PARA AVALIAR:
{roteiro}

Antes de preencher o template, confira estes 5 pontos no roteiro:
1. O gancho inicial (primeiras 2-4 frases) revela o nome da empresa ou o
   final? Se sim, isso é um problema.
2. Cada bloco (backstory, miolo, conclusão) tem pelo menos um dado, revelação
   ou pergunta nova (mini-gancho)? Ou o texto só descreve fatos em sequência
   sem nada de novo prendendo a atenção?
3. Tem algum trecho de jargão de administração/mercado sem explicação em
   linguagem simples logo depois?
4. O final é específico dessa história ou poderia estar em qualquer vídeo
   do canal (frase genérica tipo "e essa é a lição que fica")?
5. Tem algum trecho onde a descrição visual (VISUAL:) parece um momento
   único que NÃO existe pronto em banco de stock? ATENÇÃO: o objetivo é o
   CONTRÁRIO do que parece - "VISUAL: b-roll genérico de..." é o formato
   CORRETO e nunca deve ser marcado como problema, porque banco de stock
   tem chuveiro de vídeo genérico. O problema real é quando o roteiro pede
   algo hiper-específico da empresa (ex: "VISUAL: foto do CEO assinando
   ESSE contrato específico em 2016") sem marcar [ARQUIVO REAL] - aí sim é
   pra reprovar, e a correção é ADICIONAR [ARQUIVO REAL] ou trocar por algo
   MAIS genérico, nunca pedir pra ficar mais específico ainda.
6. A palavra "mini-gancho" (ou "bloco", "passo", "backstory", "miolo")
   aparece ESCRITA literalmente em alguma linha NARRAÇÃO? Isso é sempre
   erro - essas palavras são conceito de instrução, nunca texto pra
   narrar. Exemplo do erro: "O primeiro mini-gancho: a investigação
   revelou que...".
7. CONTE os números específicos no roteiro. Faça isso de verdade, linha
   por linha, do início ao fim - NÃO pare depois de achar 2 ou 3, o
   roteiro pode ter 15, 20 ou mais. Para CADA linha NARRAÇÃO, pergunte:
   tem percentual, R$/US$, quantidade de pessoas, ou data exata aqui? Se
   sim, tem [VERIFICAR] do lado, OU é fato público muito conhecido (ex:
   ano de fundação de empresa famosa)? Liste TODOS os que não tiverem,
   não só os 2-3 primeiros que achar. Se houver 3 ou mais números
   específicos sem [VERIFICAR] e sem ser fato muito conhecido, isso é um
   problema GRAVE - roteiro pode estar inventando estatística sobre
   empresa real, o que é pior que qualquer problema de ritmo ou gancho.
8. Tem alguma PESSOA COM NOME PRÓPRIO citada (funcionário, gerente,
   cliente, participante de reunião) que não seja uma figura pública
   conhecida (CEO/fundador famoso)? Nomear uma pessoa comum e colocar
   fala ("disse que...") nela é sempre invenção, mesmo sem número junto -
   marque como problema grave igual a número sem [VERIFICAR].

TEMPLATE DE RESPOSTA (preencha exatamente assim):

NOTA DO GANCHO (0 a 10): [número]
MOTIVO: [1-2 frases]

PONTOS DE QUEDA: [liste cada um encontrado, no formato "Bloco X: [motivo]".
Se não encontrar nenhum, escreva "Nenhum encontrado".]

MINI-GANCHOS FALTANDO: [liste em qual bloco falta mini-gancho, ou escreva
"Todos os blocos têm mini-gancho"]

JARGÃO NÃO EXPLICADO: [cite o trecho, ou escreva "Nenhum encontrado"]

FECHO: [específico ou genérico - justifique em 1 frase]

VISUAIS PROBLEMÁTICOS: [cite a linha VISUAL: problemática, ou escreva
"Nenhum encontrado"]

RÓTULO DE INSTRUÇÃO VAZADO: [cite a linha se "mini-gancho"/"bloco"/"passo"
aparecer escrito na narração, ou escreva "Nenhum encontrado"]

NÚMEROS SEM VERIFICAR: [liste TODOS os números específicos sem [VERIFICAR]
que não sejam fato muito conhecido - conte o roteiro inteiro, não só o
início. Ou escreva "Nenhum encontrado"]

PESSOA INVENTADA: [cite nome e trecho se houver pessoa comum (não figura
pública) citada com nome próprio, ou escreva "Nenhuma encontrada"]

CHANCE DE RETENÇÃO: [baixa / média / alta]

MUDANÇAS OBRIGATÓRIAS: [lista objetiva do que mudar, só o essencial - se
houver qualquer item nos campos "RÓTULO DE INSTRUÇÃO VAZADO", "NÚMEROS
SEM VERIFICAR" ou "PESSOA INVENTADA", ele SEMPRE entra aqui como
obrigatório, sem exceção. Se não houver nada obrigatório, escreva "Nenhuma"]

VEREDITO: [escreva exatamente a palavra APROVADO se não houver nenhuma
mudança obrigatória, ou exatamente a palavra REPROVADO se houver pelo menos
uma mudança obrigatória. Escreva só essa palavra nesta linha, em maiúsculas,
nada mais.]
"""

METADADOS_PROMPT = """Você é especialista em metadados de YouTube (título, thumbnail, descrição,
tags) para um canal de empresas e administração. O narrador não aparece
falando no vídeo (voz é gerada), mas a THUMBNAIL usa uma foto real e fixa
do criador do canal reagindo ao tema - essa foto é o elemento central de
toda thumbnail, sempre a mesma pessoa, podendo variar a expressão (choque,
sério, apontando, surpreso) conforme o tema pedir. Sua função aqui é gerar
o que atrai o CLIQUE, não o conteúdo do vídeo em si.

TEMA: {tema}

ROTEIRO APROVADO (use só para saber os fatos e o ângulo - não repita o
roteiro na resposta):
{roteiro}

SOBRE CLICKBAIT: gerar curiosidade forte, criar um gap de informação e
exagerar a tensão da história É o trabalho de título e thumbnail - isso
não é proibido, é esperado. O que é proibido é PROMETER algo que o roteiro
não entrega (ex: dizer "faliu" se a empresa não faliu, ou insinuar um
escândalo que não existe no roteiro). A régua é entrega, não intensidade:
pode exagerar o tom, não pode inventar o fato.

Preencha exatamente este template, sem pular nenhum campo. Os textos entre
colchetes abaixo (como "[abordagem: número ou dado]") são SÓ instrução de
qual abordagem usar em cada linha - não inclua esse texto entre colchetes
na sua resposta, escreva SOMENTE o título final em cada linha.

TÍTULOS (gere 5 opções, cada uma com abordagem diferente):
1. (abordagem: número ou dado - mas escreva só o título, sem esse rótulo)
2. (abordagem: pergunta/curiosidade - mas escreva só o título)
3. (abordagem: contradição ou ironia - mas escreva só o título)
4. (abordagem: comparação, ex: "Empresa X vs Empresa Y" - só o título)
5. (abordagem: urgência/atualidade - mas escreva só o título)
Regra: máximo 60 caracteres por título. Pode ser forte e provocador, mas
tudo que o título afirmar ou insinuar tem que estar de fato no roteiro.

THUMBNAIL DETALHADA (descreva como se fosse instruir um designer que nunca
viu o vídeo - seja específico, não genérico):
- FOTO DO CRIADOR (elemento central, sempre presente): [que expressão facial
  combina com este tema especificamente - ex: "olhar de choque, sobrancelha
  levantada" ou "sério, olhando direto pra câmera" ou "apontando pra trás,
  pro elemento gráfico"] e [posição na imagem, ex: "ocupando o terço direito,
  da cintura pra cima"]
- ELEMENTO GRÁFICO/DE FUNDO DE APOIO: [o que reforça o tema atrás ou ao lado
  da foto - logo/produto real da empresa, gráfico de crescimento/queda,
  imagem simbólica do setor]
- TEXTO NA THUMBNAIL: [3 a 5 palavras no máximo - a frase exata que vai
  aparecer escrita em cima da imagem]
- POSIÇÃO DO TEXTO: [ex: canto superior esquerdo, ocupando um terço da
  imagem - sem sobrepor a foto do criador]
- CORES: [paleta de 2 a 3 cores com contraste alto entre fundo e texto -
  cite os tons, ex: "fundo azul escuro quase preto, texto amarelo vibrante"]
- ELEMENTO GRÁFICO EXTRA: [opcional - seta, círculo vermelho destacando algo,
  número gigante - só se ajudar a composição, sem poluir]
- REFERÊNCIA DE ESTILO: [cite um estilo comparável de thumbnail que já
  funciona no nicho, ex: "estilo canal de negócios/finanças com apresentador
  reagindo, contraste forte"]
- ONDE CONSEGUIR A IMAGEM DE FUNDO: [termo de busca sugerido em banco de
  stock gratuito, ou "logo/produto real da empresa via imprensa" se for
  o caso]

DESCRIÇÃO DO VÍDEO (100 a 150 palavras - as 2 primeiras frases têm que
funcionar sozinhas como gancho, pois aparecem no preview de busca do
YouTube):
[texto da descrição]

TAGS (10 a 15 tags separadas por vírgula, misturando termos amplos do nicho
com termos específicos deste tema):
[lista de tags]
"""

REFERENCIA_PROMPT = """Você analisa títulos de vídeos de MAIOR SUCESSO (mais visualizações) de
canais de referência do nicho de empresas/negócios no YouTube, pra entender
o padrão por trás do que funciona - e depois gera temas NOVOS e originais
seguindo esse mesmo padrão.

TÍTULOS DE MAIOR SUCESSO DOS CANAIS DE REFERÊNCIA:
{titulos_referencia}

PASSO 1 - ANÁLISE (escreva em até 4 frases):
Qual padrão aparece nesses títulos? Considere: tipo de empresa/personagem
(gigante conhecida, fundador polêmico, marca do dia a dia), tipo de conflito
(queda, ascensão, disputa, golpe, decisão fatal), e o gatilho de curiosidade
usado (número grande, comparação, pergunta, contradição).

PASSO 2 - GERAÇÃO DE TEMAS:
Gere 6 temas NOVOS de casos reais (empresas brasileiras ou internacionais,
podem ser conhecidas ou pouco exploradas no YouTube) que sigam o mesmo
padrão de sucesso identificado no passo 1. NÃO repita nenhum tema que já
apareça na lista de referência acima - o objetivo é achar histórias
equivalentes em potencial que ainda não foram tão exploradas.

REGRA DE FORMATO IMPORTANTE: cada tema é uma descrição NEUTRA e curta do
assunto (o que vai ser pesquisado e roteirizado) - NÃO é o título chamativo
do vídeo. Título de clickbait, letra maiúscula, ponto de exclamação e texto
entre parênteses são proibidos aqui - isso é trabalho de outro agente, mais
na frente. Nunca invente palavra que não existe em português - se não
souber o nome certo de uma empresa ou termo, use uma descrição genérica em
vez de arriscar um nome errado. NÃO coloque aspas em volta do tema. NÃO
adicione explicação, análise ou justificativa depois do tema na mesma
linha (nada de "- conflito:", "- gatilho:" ou qualquer texto extra após o
tema) - a linha numerada contém SÓ o tema, nada mais, e sempre em
português.

Exemplo de formato CERTO (uma linha, sem aspas, sem explicação depois):
A falência da Mesbla e por que a Renner sobreviveu no mesmo período

Exemplo de formato ERRADO (não faça isso de jeito nenhum):
"A INACREDITÁVEL QUEDA DA MESBLA!!" - conflito: falência, gatilho: número

Preencha exatamente este formato:

ANÁLISE: [sua análise do padrão]

TEMAS SUGERIDOS (só o tema em cada linha, sem aspas, sem explicação):
1. [tema]
2. [tema]
3. [tema]
4. [tema]
5. [tema]
6. [tema]
"""

PROMPT_IMAGEM_PROMPT = """Você escreve prompts de edição de imagem por IA (formato Gemini), a partir
da descrição de expressão/pose que outro agente já decidiu para a thumbnail
deste vídeo. O objetivo final é o criador tirar UMA foto base de rosto/
corpo e usar esse prompt pra gerar a variação de expressão certa pra cada
vídeo, sem precisar fazer sessão de foto nova toda vez.

DESCRIÇÃO DA FOTO NECESSÁRIA PARA ESTA THUMBNAIL (decidida pelo agente
anterior):
{descricao_foto}

Escreva um prompt em português, pronto pra colar direto no Gemini junto com
a foto base, seguindo estas regras:

- PRESERVAÇÃO DE IDENTIDADE (a regra mais importante): instrua explicitamente
  a manter o mesmo rosto, a mesma estrutura facial, o mesmo tom de pele,
  cabelo e roupa da foto original - só mudar expressão e pose, nunca trocar
  a pessoa ou os traços dela.
- REALISMO: peça foto realista, sem estilo cartoon, ilustração ou pintura -
  textura de pele natural, poros, iluminação natural e consistente com a
  foto original, sem parecer "gerada por IA" ou suavizada demais.
- Descreva a expressão pedida em termos de MÚSCULOS DO ROSTO (sobrancelhas,
  olhos, boca, ângulo da cabeça) em vez de só nomear a emoção - só escrever
  "surpreso" gera resultado genérico e artificial; descrever "sobrancelhas
  levantadas, olhos arregalados, boca levemente aberta" gera resultado
  muito mais natural.
- Se a thumbnail pede pose de apontar ou gesto com a mão, descreva o braço,
  a mão e a direção exata do gesto.
- Peça manutenção do enquadramento pedido (da cintura pra cima, ou só
  rosto/ombros) e fundo neutro ou desfocado, pra facilitar remover o fundo
  depois na composição da thumbnail.
- Não peça texto, logo ou elemento gráfico na imagem - isso é adicionado
  depois, na composição da thumbnail. A IA de imagem só cuida da pessoa.

Preencha este template:

PROMPT PARA O GEMINI:
[texto pronto pra colar, em 1 parágrafo corrido, começando com "Edite esta
foto para..."]

DICA DE USO: [1 frase com um ajuste prático - ex: gerar 2-3 variações e
escolher a mais natural, ou reenviar pedindo pra suavizar se saiu exagerado]
"""


# =========================================================================
# FUNÇÃO BASE DE CHAMADA AO LLM
# =========================================================================

_modelo_groq_confirmado = None  # cache do primeiro modelo da lista que funcionou
_modelos_groq_ao_vivo = None  # cache da lista real da conta, consultada 1x por execução

# Categorias que não servem pra chat/texto de propósito geral - filtradas
# fora da lista ao vivo. Checa SUBSTRING (não só prefixo) porque nomes como
# "meta-llama/llama-prompt-guard-2-22m" e "openai/gpt-oss-safeguard-20b" têm
# "guard" no MEIO do nome, não no início - um filtro de prefixo deixava
# passar e o pipeline tentava usar um classificador de segurança como se
# fosse modelo de chat (erro na hora, óbvio em retrospecto).
_PALAVRAS_MODELO_IGNORAR = (
    "whisper",   # transcrição de áudio
    "guard",     # classificador de segurança/moderação (prompt-guard, safeguard)
    "tts",       # texto-pra-voz
    "playai",    # texto-pra-voz
    "orpheus",   # texto-pra-voz (canopylabs/orpheus-*)
    "compound",  # agente com ferramentas embutidas, formato de chamada diferente
)


def _obter_modelos_groq_ao_vivo():
    """
    Consulta a API do Groq pra saber quais modelos a SUA chave específica
    pode usar agora - em vez de depender de uma lista fixa que erra sempre
    que a conta não tem acesso a um modelo específico, ou o catálogo muda.
    """
    global _modelos_groq_ao_vivo
    if _modelos_groq_ao_vivo is not None:
        return _modelos_groq_ao_vivo
    try:
        resposta = client_groq.models.list()
        ids = [
            m.id
            for m in resposta.data
            if not any(p in m.id.lower() for p in _PALAVRAS_MODELO_IGNORAR)
        ]
        print(f"    (modelos disponíveis nessa chave Groq: {', '.join(ids)})")
        _modelos_groq_ao_vivo = ids
    except Exception as e:
        print(f"    Aviso: não consegui consultar a lista ao vivo do Groq ({e}).")
        _modelos_groq_ao_vivo = []
    return _modelos_groq_ao_vivo


def _kwargs_extra_para_modelo(modelo):
    """
    Modelos gpt-oss da Groq (gpt-oss-120b, gpt-oss-20b) são modelos de
    RACIOCÍNIO - por padrão gastam uma parte do orçamento de max_tokens
    "pensando" internamente antes de escrever a resposta visível. Com o
    prompt do roteiro (que é grande, cheio de regras), esse raciocínio
    interno já consumiu o max_tokens INTEIRO antes de chegar a escrever
    o roteiro - resultado real: resposta cortada com 0 linhas NARRAÇÃO,
    mesmo com max_tokens=8192. "low" reduz esse raciocínio ao mínimo,
    sobrando orçamento de verdade pra escrever a resposta.
    """
    if "gpt-oss" in modelo:
        return {"reasoning_effort": "low"}
    return {}


def _chamar_groq_com_fallback(messages, temperature, max_tokens):
    global _modelo_groq_confirmado

    if _modelo_groq_confirmado:
        ordem = [_modelo_groq_confirmado] + [
            m for m in MODELOS_GROQ_FALLBACK if m != _modelo_groq_confirmado
        ]
    else:
        ordem = list(MODELOS_GROQ_FALLBACK)

    ultimo_erro = None
    for modelo in ordem:
        try:
            resposta = client_groq.chat.completions.create(
                model=modelo,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=_kwargs_extra_para_modelo(modelo),
            )
            if _modelo_groq_confirmado != modelo:
                print(f"    (usando modelo Groq: {modelo})")
                _modelo_groq_confirmado = modelo
            return resposta
        except Exception as e:
            print(
                f"    Aviso: modelo Groq '{modelo}' falhou "
                f"({type(e).__name__}) - tentando o próximo da lista..."
            )
            ultimo_erro = e
            continue

    # A lista fixa inteira falhou (modelo indisponível na conta, ou todos
    # com cota estourada de uma vez) - última cartada: pergunta direto pro
    # Groq quais modelos essa chave específica realmente pode usar, e
    # tenta os que ainda não foram tentados.
    print("    Toda a lista fixa falhou - consultando modelos disponíveis ao vivo...")
    disponiveis = _obter_modelos_groq_ao_vivo()
    for modelo in disponiveis:
        if modelo in ordem:
            continue  # já tentado acima
        try:
            resposta = client_groq.chat.completions.create(
                model=modelo,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=_kwargs_extra_para_modelo(modelo),
            )
            print(f"    (usando modelo Groq: {modelo} - achado pela consulta ao vivo)")
            _modelo_groq_confirmado = modelo
            return resposta
        except Exception as e:
            print(
                f"    Aviso: modelo Groq '{modelo}' (da lista ao vivo) falhou "
                f"({type(e).__name__}) - tentando o próximo..."
            )
            ultimo_erro = e
            continue

    raise RuntimeError(
        "Nenhum modelo do Groq funcionou, nem da lista fixa nem da consulta "
        "ao vivo da conta. Pode ser cota diária estourada em todos ao mesmo "
        "tempo (espere um pouco e tente de novo), mas também pode ser um "
        "modelo com limite de tokens-por-minuto baixo recebendo um pedido "
        f"grande demais pra ele - o erro real do último modelo foi:\n"
        f"{ultimo_erro}\n"
        "Confira console.groq.com/dashboard/limits pra ver a cota de cada "
        "modelo específico."
    ) from ultimo_erro


def chamar_llm(prompt, temperature=0.7, max_tokens=8192, avisar_corte=True):
    """
    max_tokens=8192 é um teto generoso - o valor anterior (4096) já cortou
    geração de roteiro E de expansão no meio, confirmado em log real (o
    aviso "resposta CORTADA" apareceu duas vezes na mesma execução). Um
    roteiro de 1300+ palavras em português, mais as linhas VISUAL de cada
    frase, facilmente passa de 4096 tokens.
    servidor pode aplicar um limite de geração bem menor que o necessário
    pra um roteiro de 1300+ palavras, cortando a resposta no meio sem
    avisar, não importa o que o prompt peça.
    """
    mensagens = [{"role": "user", "content": prompt}]

    if USAR_NUVEM:
        if not client_groq:
            raise RuntimeError(
                "USAR_NUVEM está True mas GROQ_API_KEY não foi configurada. "
                "Crie uma chave grátis em console.groq.com/keys e coloque "
                "no .env, ou mude USAR_NUVEM para False pra usar o Ollama local."
            )
        resposta = _chamar_groq_com_fallback(mensagens, temperature, max_tokens)
    else:
        resposta = client_local.chat.completions.create(
            model=MODEL,
            messages=mensagens,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    escolha = resposta.choices[0]
    if avisar_corte and getattr(escolha, "finish_reason", None) == "length":
        print(
            f"    Aviso: resposta CORTADA por limite de tokens "
            f"(max_tokens={max_tokens}). Se isso afetar o roteiro, "
            "aumente max_tokens na chamada."
        )
    return escolha.message.content or ""


# =========================================================================
# AGENTE 1 - PESQUISADOR (sem chave de API, usa RSS do Google News)
# =========================================================================

def pesquisar_temas_em_alta(quantidade=8):
    """
    Roda várias buscas com termos que tendem a trazer histórias com tensão
    narrativa (crise, decisão de risco, ascensão/queda, escândalo) em vez
    de matéria institucional/acadêmica genérica sobre "administração".
    """
    import feedparser
    from urllib.parse import quote

    queries = [
        "empresa crise decisão",
        "empresa faliu escândalo",
        "ascensão queda empresa",
        "estratégia empresarial polêmica",
        "empresa processo bilionário",
        "fundador empresa erro",
    ]

    temas = []
    vistos = set()
    for q in queries:
        termo_codificado = quote(q)
        url = (
            f"https://news.google.com/rss/search?q={termo_codificado}"
            "&hl=pt-BR&gl=BR&ceid=BR:pt-419"
        )
        feed = feedparser.parse(url)
        for entry in feed.entries[:3]:
            if entry.title not in vistos:
                vistos.add(entry.title)
                temas.append(entry.title)
        if len(temas) >= quantidade:
            break

    return temas[:quantidade]


# =========================================================================
# AGENTE 1B - REFERÊNCIA (vídeos que mais renderam em canais do nicho)
# =========================================================================

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def _youtube_get(endpoint, params):
    params = {**params, "key": YOUTUBE_KEY}
    resp = requests.get(f"{YOUTUBE_API_BASE}/{endpoint}", params=params)
    resp.raise_for_status()
    return resp.json()


def obter_channel_id(handle):
    """Resolve o ID interno do canal a partir do @handle."""
    dados = _youtube_get("channels", {"part": "id", "forHandle": handle})
    itens = dados.get("items", [])
    if not itens:
        return None
    return itens[0]["id"]


def obter_playlist_uploads(channel_id):
    """Todo canal tem uma playlist automática com todos os uploads."""
    dados = _youtube_get(
        "channels", {"part": "contentDetails", "id": channel_id}
    )
    itens = dados.get("items", [])
    if not itens:
        return None
    return itens[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def obter_ids_dos_videos(playlist_id, limite=100):
    """Pagina a playlist de uploads até juntar 'limite' IDs de vídeo."""
    ids = []
    pagina_token = None
    while len(ids) < limite:
        params = {
            "part": "contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if pagina_token:
            params["pageToken"] = pagina_token
        dados = _youtube_get("playlistItems", params)
        for item in dados.get("items", []):
            ids.append(item["contentDetails"]["videoId"])
        pagina_token = dados.get("nextPageToken")
        if not pagina_token:
            break
    return ids[:limite]


def obter_top_videos_por_views(video_ids, top_n=8):
    """Busca estatísticas em lotes de 50 (limite da API) e ordena por views."""
    todos = []
    for i in range(0, len(video_ids), 50):
        lote = video_ids[i : i + 50]
        dados = _youtube_get(
            "videos", {"part": "snippet,statistics", "id": ",".join(lote)}
        )
        for item in dados.get("items", []):
            todos.append(
                {
                    "titulo": item["snippet"]["title"],
                    "views": int(item["statistics"].get("viewCount", 0)),
                }
            )
    todos.sort(key=lambda v: v["views"], reverse=True)
    return todos[:top_n]


def buscar_top_videos_canal(handle, top_n=8):
    """Pipeline completo: handle -> channel_id -> uploads -> top por views."""
    channel_id = obter_channel_id(handle)
    if not channel_id:
        return []
    playlist_id = obter_playlist_uploads(channel_id)
    if not playlist_id:
        return []
    video_ids = obter_ids_dos_videos(playlist_id, limite=100)
    return obter_top_videos_por_views(video_ids, top_n)


def buscar_referencias(canais=None, top_n_por_canal=8):
    """
    Roda buscar_top_videos_canal para cada canal em CANAIS_REFERENCIA e
    devolve uma lista única de títulos (sem duplicar), ordenada por views
    dentro de cada canal.
    """
    if not YOUTUBE_KEY:
        return []
    canais = canais or CANAIS_REFERENCIA
    titulos = []
    vistos = set()
    for handle in canais:
        try:
            top = buscar_top_videos_canal(handle, top_n=top_n_por_canal)
        except requests.HTTPError as e:
            print(f"  Aviso: falha ao buscar '{handle}' ({e}) - pulando.")
            continue
        for v in top:
            if v["titulo"] not in vistos:
                vistos.add(v["titulo"])
                titulos.append(v["titulo"])
    return titulos


def limpar_tema(texto):
    """
    Sanitização de formato - NÃO corrige palavra inventada (isso não dá pra
    detectar com regex), só limpa formatação de clickbait que o modelo às
    vezes gera mesmo quando o prompt pede pra não fazer isso.

    Limitação conhecida: ao converter um título todo em CAIXA ALTA pra Title
    Case, siglas reais (BYD, CEO, IPO) também perdem a caixa alta - é um
    trade-off aceitável, já que não dá pra distinguir sigla de "grito" só
    com regex. Revise o tema escolhido antes de seguir se isso incomodar.
    """
    texto = texto.strip().strip('"').strip("'").strip()

    # remove explicação colada depois do tema, no padrão 'tema" - explicação'
    # ou 'tema - explicação em inglês' que o modelo às vezes gera mesmo
    # quando o prompt pede pra não fazer isso
    texto = re.sub(r'"\s*-\s*.+$', "", texto)
    texto = texto.strip().strip('"').strip("'").strip()

    # remove "!" e "?" em qualquer posição (não só no final)
    texto = re.sub(r"[!?]+", "", texto)
    texto = re.sub(r"\s{2,}", " ", texto)

    # se a maior parte das letras estiver em maiúscula, o título inteiro
    # provavelmente é "grito" (CAPS LOCK) - converte pra Title Case de vez
    letras = [c for c in texto if c.isalpha()]
    if letras and sum(1 for c in letras if c.isupper()) / len(letras) > 0.5:
        texto = texto.title()

    return texto.strip(" .")


def gerar_temas_por_referencia(titulos_referencia, quantidade=6):
    if not titulos_referencia:
        return "", []
    lista_formatada = "\n".join(f"- {t}" for t in titulos_referencia)
    prompt = REFERENCIA_PROMPT.format(titulos_referencia=lista_formatada)
    resposta = chamar_llm(prompt, temperature=0.8, max_tokens=1500)
    temas = re.findall(r"^\d+\.\s*(.+)$", resposta, re.MULTILINE)
    temas = [limpar_tema(t) for t in temas]
    return resposta, temas[:quantidade]


# =========================================================================
# AGENTE 2 - ROTEIRISTA
# =========================================================================

def escrever_roteiro(tema, roteiro_anterior=None, mudancas_obrigatorias=None, historico_mudancas=None):
    prompt = ROTEIRO_PROMPT.format(tema=tema)
    if roteiro_anterior and mudancas_obrigatorias:
        prompt += (
            "\n\nJá existe uma versão anterior deste roteiro, que foi REPROVADA "
            "pelo crítico. Sua tarefa agora é REVISAR essa versão, não escrever "
            "outra do zero. Mantenha tudo que já estava bom e mude APENAS o que "
            "está listado como obrigatório abaixo - se um trecho não foi citado "
            "no apontamento, deixe ele como está.\n\n"
            f"VERSÃO ANTERIOR (revise a partir dela):\n{roteiro_anterior}\n\n"
            f"MUDANÇAS OBRIGATÓRIAS (corrija só isso, nada além):\n"
            f"{mudancas_obrigatorias}\n\n"
            "DICA DE EXECUÇÃO - se a mudança pedir mini-gancho num bloco que "
            "não tem: a forma mais fácil é INSERIR uma frase nova no meio do "
            "bloco (um dado numérico, uma pergunta retórica, ou uma pequena "
            "revelação) - você não precisa reescrever o bloco inteiro, só "
            "adicionar essa frase nova no meio do texto que já existe. Faça "
            "isso em CADA bloco que a mudança obrigatória apontar, não só em "
            "um."
        )

        # ESCALAÇÃO: se já reprovou 2+ vezes, o ajuste pontual ("insira uma
        # frase") não está resolvendo - muda de estratégia pra reescrita
        # completa do bloco problemático, em vez de continuar cutucando
        # com o mesmo tipo de correção pequena que já não funcionou.
        if historico_mudancas and len(historico_mudancas) >= 2:
            print(
                f"    Aviso: {len(historico_mudancas)}ª reprovação seguida - "
                "escalando pra reescrita completa do(s) bloco(s) problemático(s) "
                "em vez de ajuste pontual."
            )
            historico_formatado = "\n---\n".join(
                f"Tentativa {i}: {m}" for i, m in enumerate(historico_mudancas, 1)
            )
            prompt += (
                "\n\nATENÇÃO - ESCALAÇÃO (leia antes de revisar): este "
                f"roteiro já foi reprovado {len(historico_mudancas)} vezes "
                "seguidas. O ajuste pontual ('insira uma frase') não está "
                "resolvendo o problema de verdade - a estrutura do bloco "
                "provavelmente precisa mudar, não só ganhar uma frase a "
                "mais. Desta vez, REESCREVA POR COMPLETO cada bloco "
                "(backstory, miolo ou conclusão) onde a mudança obrigatória "
                "aponta problema, do zero, mantendo os mesmos fatos mas "
                "com estrutura diferente - não tente só remendar o texto "
                "anterior nesses blocos específicos.\n\n"
                "HISTÓRICO DE TODOS OS PEDIDOS ANTERIORES (pra você NÃO "
                "repetir o mesmo padrão de correção que já falhou nessas "
                "tentativas):\n"
                f"{historico_formatado}"
            )
    return chamar_llm(prompt, temperature=0.8, max_tokens=8192)


# =========================================================================
# AGENTE 3 - CRÍTICO
# =========================================================================

def avaliar_roteiro(roteiro, mudancas_pedidas_antes=None):
    prompt = AVALIACAO_PROMPT.format(roteiro=roteiro)
    if mudancas_pedidas_antes and not mudancas_sao_vazias(mudancas_pedidas_antes):
        prompt += (
            "\n\nCONTEXTO: na rodada de avaliação ANTERIOR, você (ou outra "
            "avaliação deste mesmo roteiro) pediu estas mudanças:\n"
            f"{mudancas_pedidas_antes}\n\n"
            "O roteirista revisou o texto tentando atender exatamente essa "
            "lista. REGRA IMPORTANTE: não peça pra desfazer algo que está "
            "nessa lista acima - se você pediu pra ADICIONAR um elemento, "
            "não peça pra REMOVER esse mesmo elemento agora, e vice-versa. "
            "Mudar de ideia sobre o mesmo ponto trava o roteiro num ciclo "
            "sem fim. Avalie apenas: (1) os itens acima foram resolvidos? "
            "(2) sobrou algum problema NOVO e DIFERENTE dos que já foram "
            "listados? Só liste como obrigatório o que for genuinamente "
            "novo ou genuinamente não resolvido."
        )
    return chamar_llm(prompt, temperature=0.2, max_tokens=2500)


def mudancas_sao_vazias(mudancas_texto):
    """Verifica se o campo MUDANÇAS OBRIGATÓRIAS está de fato vazio
    ('Nenhuma' ou variações). Usado pra travar uma contradição comum em
    modelo pequeno: escrever VEREDITO: APROVADO mas ainda assim listar
    uma mudança obrigatória pendente no campo acima."""
    if not mudancas_texto:
        return True
    texto = mudancas_texto.strip().lower().rstrip(".")
    return texto in ("nenhuma", "nenhum", "") or len(texto) < 3


def extrair_mudancas_obrigatorias(avaliacao_texto):
    """Pega só o campo 'MUDANÇAS OBRIGATÓRIAS' do template do crítico -
    em vez de mandar a avaliação inteira de volta pro roteirista."""
    match = re.search(
        r"MUDANÇAS OBRIGATÓRIAS:\s*(.+?)(?:\n\s*VEREDITO:|\Z)",
        avaliacao_texto,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    return avaliacao_texto  # fallback: manda tudo se não achar o campo


def extrair_veredito(avaliacao_texto):
    """Lê a linha 'VEREDITO:' do template fixo de avaliação."""
    match = re.search(r"VEREDITO:\s*(APROVADO|REPROVADO)", avaliacao_texto, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    # modelo pequeno pode não seguir o template à risca - fallback simples
    return "aprovado" if "aprovado" in avaliacao_texto.lower()[-200:] else "reprovado"


# =========================================================================
# AGENTE 4 - EDITOR (busca real de b-roll no Pexels)
# =========================================================================

def extrair_linhas_visuais(roteiro):
    return re.findall(r"VISUAL:\s*(.+)", roteiro)


# Prefixos que só dizem o TIPO de plano ("b-roll genérico de", "animação
# de") e não ajudam a busca - se sobrarem no termo, o Pexels devolve
# resultado aleatório.
_RUIDO_TERMO_VISUAL = (
    "b-roll genérico de", "b-roll generico de", "b-roll de", "b roll de",
    "imagem de", "imagens de", "vídeo de", "video de", "cena de",
    "animação de", "animacao de", "plano de", "close de", "tomada de",
)

# Último recurso quando nem o termo traduzido nem as versões mais curtas
# acham vídeo: melhor um clipe genérico de ambiente corporativo do que o
# trecho ficar sem nenhuma imagem pra editar.
TERMO_BROLL_GENERICO = "business office"


# Palavras de ligação que não fazem sentido no fim de um termo de busca
_LIGACOES_EN = {"in", "on", "at", "of", "a", "an", "the", "with", "and", "to", "for"}


def _limpar_termo_busca(texto_bruto):
    """
    A resposta do modelo pode vir com sobra: linha de raciocínio, aspas,
    ponto final, ou uma frase inteira antes do termo. Aqui sobra só o que
    o Pexels entende - no máximo 5 palavras, minúsculas, sem pontuação.
    """
    if not texto_bruto:
        return ""
    linhas = [l.strip() for l in texto_bruto.strip().splitlines() if l.strip()]
    if not linhas:
        return ""
    termo = linhas[-1]  # modelos de raciocínio deixam o resultado por último
    termo = re.sub(
        r"^(termo de busca|search term|query|termo|resposta)\s*[:\-]\s*",
        "",
        termo,
        flags=re.IGNORECASE,
    )
    termo = re.sub(r"[^\w\s-]", " ", termo, flags=re.UNICODE)
    palavras = termo.split()[:5]
    # corte em 5 palavras pode terminar em preposição solta ("price tag
    # changing in a") - isso só atrapalha a busca no Pexels
    while palavras and palavras[-1].lower() in _LIGACOES_EN:
        palavras.pop()
    return " ".join(palavras).lower()


_PALAVRAS_VAZIAS_PT = {
    "com", "sem", "para", "por", "uma", "uns", "umas", "dos", "das", "que",
    "aos", "nas", "nos", "seu", "sua", "ele", "ela", "sendo", "num", "numa",
}


def _termo_de_emergencia(termo_pt):
    """
    Plano B quando o modelo não devolve termo aproveitável: usa a própria
    descrição em português, sem o prefixo decorativo e sem acento. Não é
    ideal (o Pexels é indexado em inglês), mas ainda casa nome próprio e
    palavra igual nos dois idiomas - e é melhor que buscar string vazia.
    """
    texto = termo_pt.lower()
    for ruido in _RUIDO_TERMO_VISUAL:
        texto = texto.replace(ruido, " ")
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^\w\s-]", " ", texto)
    palavras = [
        palavra for palavra in texto.split()
        if len(palavra) > 2 and palavra not in _PALAVRAS_VAZIAS_PT
    ]
    return " ".join(palavras[:4])


def traduzir_termo_busca(termo_pt):
    """
    Pexels é indexado majoritariamente em inglês, e busca funciona muito
    melhor com 2-5 palavras-chave do que com uma frase descritiva inteira.
    Este agente converte a descrição visual (em português, às vezes longa)
    num termo de busca curto e em inglês.

    O max_tokens aqui era 30 e isso QUEBRAVA a busca na prática: os
    modelos gpt-oss da Groq são de raciocínio e gastam parte do orçamento
    "pensando" antes de escrever, então com 30 tokens a resposta visível
    saía cortada no meio ("crowded", "generic expl", "vicious") - foi isso
    que encheu o log de "resposta CORTADA" em toda linha VISUAL e deixou
    um trecho sem clipe nenhum. 300 dá folga pro raciocínio, e a limpeza
    de _limpar_termo_busca garante que ainda assim só o termo curto chega
    no Pexels.
    """
    prompt = (
        "Converta esta descrição de imagem/vídeo em um termo de busca curto "
        "em INGLÊS para um banco de vídeos de stock (2 a 5 palavras-chave, "
        "sem frase completa, sem pontuação). Responda APENAS com o termo de "
        "busca, nada mais.\n\n"
        f"Descrição: {termo_pt}"
    )
    try:
        resposta = chamar_llm(
            prompt, temperature=0.3, max_tokens=300, avisar_corte=False
        )
    except Exception as e:
        print(
            f"    Aviso: falha ao traduzir o termo ({type(e).__name__}) - "
            "usando a descrição original como busca."
        )
        return _termo_de_emergencia(termo_pt)
    return _limpar_termo_busca(resposta) or _termo_de_emergencia(termo_pt)


def _escolher_arquivo_video(video_files):
    """
    A API do Pexels retorna vários arquivos por vídeo (SD, HD, 4K...) sem
    garantia de ordem - pega o de qualidade "hd" quando existir, senão usa
    o primeiro disponível. Evita baixar um arquivo desnecessariamente
    grande (4K) ou desnecessariamente ruim (SD) só por estar em outra
    posição na lista.
    """
    for vf in video_files:
        if vf.get("quality") == "hd":
            return vf
    return video_files[0]


def buscar_broll_pexels(termo_busca, por_pagina=3, avisar_vazio=True):
    if not PEXELS_KEY:
        print("    Aviso: PEXELS_API_KEY não configurada - pulando busca de b-roll.")
        return []
    headers = {"Authorization": PEXELS_KEY}
    resp = requests.get(
        "https://api.pexels.com/v1/videos/search",
        headers=headers,
        params={"query": termo_busca, "per_page": por_pagina},
        timeout=30,
    )
    if resp.status_code != 200:
        print(
            f"    Aviso: Pexels retornou erro {resp.status_code} pra "
            f"'{termo_busca}' - {resp.text[:200]}"
        )
        return []
    dados = resp.json()
    videos = dados.get("videos", [])
    if not videos and avisar_vazio:
        print(f"    Aviso: nenhum resultado no Pexels pra '{termo_busca}'.")
    return [
        {
            "id": v["id"],
            "preview": _escolher_arquivo_video(v["video_files"])["link"],
            "duracao_s": v["duration"],
        }
        for v in videos
    ]


def buscar_broll_com_alternativas(termo_en, termo_pt):
    """
    Tenta o termo traduzido e, se o Pexels não devolver nada, vai
    encurtando até um termo genérico - em vez de deixar o trecho sem
    clipe (foi o que aconteceu com o trecho 05 do último roteiro, que
    ficou na lista de "sem clipe baixado").
    """
    palavras = termo_en.split()
    tentativas = [termo_en]
    if len(palavras) > 2:
        tentativas.append(" ".join(palavras[:2]))
    if palavras:
        tentativas.append(palavras[0])
    tentativas.append(_termo_de_emergencia(termo_pt))
    tentativas.append(TERMO_BROLL_GENERICO)

    ja_tentados = set()
    for posicao, tentativa in enumerate(tentativas):
        tentativa = tentativa.strip()
        if not tentativa or tentativa in ja_tentados:
            continue
        ja_tentados.add(tentativa)
        if posicao > 0:
            print(f"      (sem resultado - tentando termo mais amplo: '{tentativa}')")
        resultados = buscar_broll_pexels(tentativa, avisar_vazio=False)
        if resultados:
            return resultados

    print(f"    Aviso: nenhum resultado no Pexels nem no termo genérico pra '{termo_en}'.")
    return []


def montar_lista_broll(roteiro):
    termos = extrair_linhas_visuais(roteiro)
    resultado = {}
    for termo in termos:
        if "[ARQUIVO REAL]" in termo.upper() or "ARQUIVO REAL" in termo.upper():
            # isso precisa vir de imprensa/arquivo real, nunca vai achar no
            # banco de stock - não vale a pena nem tentar buscar
            resultado[termo] = {"tipo": "arquivo_real_necessario", "resultados": []}
            continue
        termo_busca_en = traduzir_termo_busca(termo)
        print(f"    Buscando '{termo}' como '{termo_busca_en}'...")
        resultado[termo] = buscar_broll_com_alternativas(termo_busca_en, termo)
    return resultado


def _slugificar(texto, tamanho_max=40):
    """Transforma o termo de busca num nome de arquivo seguro (sem acento,
    sem espaço, sem caractere especial)."""
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-zA-Z0-9]+", "_", texto).strip("_").lower()
    return texto[:tamanho_max] or "clipe"


def baixar_broll(broll_dict, pasta_destino, por_termo=1):
    """
    Baixa os clipes de b-roll encontrados pra uma pasta local, prontos pra
    arrastar direto no editor de vídeo - em vez de só listar o link, que
    exigia abrir um por um manualmente.

    por_termo=1 baixa só o melhor resultado de cada trecho do roteiro
    (mais rápido). Aumente pra 2 ou 3 se quiser opções pra escolher
    visualmente qual encaixa melhor antes de editar.

    Retorna (baixados, pulados) - duas listas pra você ver o que faltou.
    """
    pasta_destino.mkdir(parents=True, exist_ok=True)
    baixados = []
    pulados = []

    for i, (termo, dados) in enumerate(broll_dict.items(), 1):
        if isinstance(dados, dict) and dados.get("tipo") == "arquivo_real_necessario":
            pulados.append((termo, "precisa de arquivo real, não é banco de stock"))
            continue
        if not dados:
            pulados.append((termo, "nenhum resultado encontrado na busca"))
            continue

        slug = _slugificar(termo)
        candidatos = dados[:por_termo]
        for j, clipe in enumerate(candidatos, 1):
            sufixo = f"_opcao{j}" if len(candidatos) > 1 else ""
            nome_arquivo = f"{i:02d}_{slug}{sufixo}.mp4"
            caminho = pasta_destino / nome_arquivo
            try:
                resp = requests.get(clipe["preview"], timeout=60, stream=True)
                if resp.status_code != 200:
                    pulados.append((termo, f"erro {resp.status_code} ao baixar"))
                    continue
                with open(caminho, "wb") as f:
                    for pedaco in resp.iter_content(chunk_size=8192):
                        f.write(pedaco)
                print(f"    Baixado: {nome_arquivo}")
                baixados.append(nome_arquivo)
            except Exception as e:
                pulados.append((termo, f"erro ao baixar ({type(e).__name__})"))

    print(f"    {len(baixados)} clipe(s) baixado(s), {len(pulados)} pulado(s).")
    return baixados, pulados


# =========================================================================
# AGENTE 5 - METADADOS (título, thumbnail detalhada, descrição, tags)
# =========================================================================

def gerar_metadados(tema, roteiro):
    prompt = METADADOS_PROMPT.format(tema=tema, roteiro=roteiro)
    return chamar_llm(prompt, temperature=0.8, max_tokens=2000)


def extrair_descricao_foto(metadados_texto):
    """Pega o campo 'FOTO DO CRIADOR' de dentro da resposta de metadados."""
    match = re.search(
        r"FOTO DO CRIADOR.*?:\s*(.+?)(?:\n- [A-ZÀ-Ú]|\Z)",
        metadados_texto,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    return metadados_texto  # fallback: manda o texto todo se não achar o campo


# =========================================================================
# AGENTE 6 - PROMPT DE IMAGEM (gera o prompt pronto pra colar no Gemini)
# =========================================================================

def gerar_prompt_imagem(descricao_foto):
    prompt = PROMPT_IMAGEM_PROMPT.format(descricao_foto=descricao_foto)
    return chamar_llm(prompt, temperature=0.6, max_tokens=800)


def contar_palavras_narracao(roteiro):
    """Conta só as palavras dentro das linhas NARRAÇÃO, ignorando VISUAL."""
    trechos = re.findall(
        r"NARRAÇÃO:\s*(.+?)(?=NARRAÇÃO:|VISUAL:|\Z)", roteiro, re.DOTALL
    )
    return sum(len(t.split()) for t in trechos)


def expandir_roteiro(roteiro, tema, palavras_atuais, alvo_minimo=1270):
    """
    Rede de segurança: roda quando o roteiro sai curto demais mesmo depois
    do loop de revisão. Diferente do loop crítico->roteirista (que depende
    do modelo entender um apontamento abstrato), aqui a instrução é
    mecânica e direta: "está curto, desenvolva mais", o que modelo pequeno
    tende a executar melhor que "adicione mini-gancho".

    IMPORTANTE: este prompt tem as MESMAS travas factuais do roteiro
    original - sem isso, o passe de expansão já inventou uma história
    inteira de escândalo falso sobre uma empresa real (misturando um fato
    real desconexo com nomes de pessoas e números 100% fabricados), sem
    nenhum [VERIFICAR]. "Desenvolver mais" nunca pode significar "inventar
    fato novo" ou "continuar a história depois do fim".
    """
    prompt = (
        f"O roteiro abaixo tem cerca de {palavras_atuais} palavras de "
        f"narração, abaixo do mínimo de {alvo_minimo} necessário para um "
        "vídeo de 8-10 minutos. Sua tarefa é DESENVOLVER MAIS o roteiro -\n\n"
        "REGRAS QUE NÃO PODEM SER QUEBRADAS (mais importantes que o "
        "tamanho):\n"
        "- PROIBIDO inventar qualquer fato, número, nome de pessoa, data,\n"
        "  valor ou evento que não estava no roteiro original. 'Desenvolver'\n"
        "  significa reescrever com mais palavras o que já foi dito -\n"
        "  explicar melhor o raciocínio, dar mais contexto - NUNCA "
        "  adicionar um fato novo que parece plausível. Se não tem certeza\n"
        "  se um número é real, marque [VERIFICAR], nunca invente pra\n"
        "  preencher espaço.\n"
        "- PROIBIDO continuar a história depois do final que já existe. O\n"
        "  roteiro original já tem uma conclusão - não adicione um "
        "  'segundo ato' ou nova sequência de eventos depois dela. Expanda\n"
        "  POR DENTRO dos blocos que já existem, nunca por fora/depois.\n"
        "- PROIBIDO duplicar qualquer trecho do roteiro original. A "
        "  resposta final tem que ter cada fato UMA vez só.\n\n"
        "Nesta ordem de prioridade, dentro dessas regras:\n"
        "1. Desenvolva mais o MIOLO (a parte com a decisão/conflito "
        "central) - adicione mais detalhe do raciocínio de gestão e do "
        "contexto de cada etapa QUE JÁ FOI CITADA, sem trazer fato novo.\n"
        "2. Garanta que cada bloco (backstory, miolo, conclusão) tenha "
        "pelo menos um mini-gancho (dado novo, revelação pequena, "
        "pergunta) - insira uma frase nova onde faltar, mas só reformulando\n"
        "informação que já está no roteiro.\n"
        "3. Mantenha o mesmo formato: cada frase em uma linha NARRAÇÃO:, "
        "seguida numa linha separada por VISUAL:.\n\n"
        f"TEMA: {tema}\n\n"
        f"ROTEIRO ATUAL:\n{roteiro}\n\n"
        "Responda com o ROTEIRO COMPLETO revisado e expandido (não só a "
        "parte nova, o texto inteiro do início ao fim, UMA ÚNICA VEZ), sem "
        "comentário sobre a tarefa, sem repetir nomes de passo, sem "
        "adicionar um '---' ou qualquer divisor no meio do texto."
    )
    return chamar_llm(prompt, temperature=0.7, max_tokens=8192)


# =========================================================================
# ORQUESTRAÇÃO - roda os 6 agentes em sequência, com loop de correção
# =========================================================================


def gerar_video_completo(tema, max_tentativas=4):
    mudancas = None
    roteiro = None
    avaliacao = None
    historico = []  # guarda o motivo de reprovação de CADA tentativa, não só a última

    for tentativa in range(1, max_tentativas + 1):
        print(f"[Tentativa {tentativa}] Gerando roteiro para: {tema}")
        historico_mudancas = [
            item["mudancas_pedidas"] for item in historico if item["veredito"] == "reprovado"
        ]
        roteiro = escrever_roteiro(
            tema,
            roteiro_anterior=roteiro,
            mudancas_obrigatorias=mudancas,
            historico_mudancas=historico_mudancas,
        )

        # Validação: já aconteceu de o roteirista devolver algo vazio ou
        # sem o formato NARRAÇÃO:/VISUAL: (ex: recusa, erro, resposta em
        # branco) - mandar isso pro crítico só desperdiça uma tentativa
        # inteira (o crítico responde "não há roteiro pra avaliar" e conta
        # como reprovado à toa). Tenta gerar de novo, uma vez, antes de
        # gastar o ciclo completo de crítica nisso.
        if roteiro.count("NARRAÇÃO:") < 3:
            print(
                "    Aviso: roteiro devolvido parece vazio/inválido "
                f"(só {roteiro.count('NARRAÇÃO:')} linha(s) NARRAÇÃO:) - "
                "gerando de novo antes de avaliar..."
            )
            roteiro = escrever_roteiro(tema, roteiro_anterior=None, mudancas_obrigatorias=None)
            if roteiro.count("NARRAÇÃO:") < 3:
                print("    Aviso: segunda tentativa também veio inválida - avaliando mesmo assim.")

        print("  Avaliando roteiro...")
        avaliacao = avaliar_roteiro(roteiro, mudancas_pedidas_antes=mudancas)
        veredito = extrair_veredito(avaliacao)
        mudancas = extrair_mudancas_obrigatorias(avaliacao)

        if veredito == "aprovado" and not mudancas_sao_vazias(mudancas):
            print(
                "    Aviso: crítico escreveu APROVADO mas listou mudança "
                "obrigatória pendente - tratando como REPROVADO."
            )
            veredito = "reprovado"

        print(f"  Veredito: {veredito.upper()}")

        historico.append(
            {"tentativa": tentativa, "veredito": veredito, "mudancas_pedidas": mudancas}
        )

        if veredito == "aprovado":
            break

        print("  Motivo da reprovação (o que será corrigido na próxima tentativa):")
        print(" ", mudancas)
    else:
        print("  Número máximo de tentativas atingido - usando última versão.")
        print("  Pendências que NÃO foram resolvidas (ajuste manualmente se quiser):")
        print(" ", mudancas)

    palavras = contar_palavras_narracao(roteiro)
    if palavras < 1100:
        print(f"  Roteiro tem só ~{palavras} palavras de narração - rodando passe de expansão...")
        roteiro_expandido = expandir_roteiro(roteiro, tema, palavras)
        nova_contagem = contar_palavras_narracao(roteiro_expandido)

        # Trava de segurança: se "expandir" na prática quase dobrou o
        # tamanho, ou apareceu um divisor solto ("---"), é sinal de que o
        # modelo continuou a história em vez de desenvolver o que já
        # existia (já aconteceu - virou uma segunda história inventada
        # colada na primeira). Se ficou com MENOS palavras que antes, é
        # sinal de que a resposta foi cortada no meio por limite de token
        # (já aconteceu também - expansão "piorou" o roteiro). Em
        # qualquer um desses casos, descarta a expansão e fica com o
        # roteiro mais curto, mas honesto/completo, em vez do mais longo,
        # arriscado ou truncado.
        # Teto ABSOLUTO, não proporção - a expansão dispara com roteiro
        # abaixo de 1100 palavras, e o alvo é 1270-1620, então crescer
        # mais de 1.8x é NORMAL vindo de um começo bem curto (ex:
        # 700->1300 é legítimo). Um teto absoluto bem acima do alvo máximo
        # (1620) ainda pega duplicação de verdade sem rejeitar expansão
        # legítima por coincidência de proporção.
        cresceu_alem_do_razoavel = nova_contagem > 2200
        ficou_menor = nova_contagem <= palavras
        tem_divisor_solto = bool(re.search(r"^\s*-{3,}\s*$", roteiro_expandido, re.MULTILINE))
        if cresceu_alem_do_razoavel or ficou_menor or tem_divisor_solto:
            if cresceu_alem_do_razoavel:
                motivo = f"passou de {nova_contagem} palavras (provável duplicação)"
            elif ficou_menor:
                motivo = f"ficou com MENOS palavras que antes ({nova_contagem} <= {palavras}, provável corte por limite de token)"
            else:
                motivo = "tem divisor '---' solto"
            print(f"  Aviso: expansão descartada - {motivo}. Mantendo a versão de ~{palavras} palavras.")
        else:
            roteiro = roteiro_expandido
            print(f"  Depois da expansão: ~{nova_contagem} palavras.")

    print("Buscando b-roll correspondente no Pexels...")
    broll = montar_lista_broll(roteiro)

    print("Gerando título, thumbnail, descrição e tags...")
    metadados = gerar_metadados(tema, roteiro)

    print("Gerando prompt de edição de foto para o Gemini...")
    descricao_foto = extrair_descricao_foto(metadados)
    prompt_imagem = gerar_prompt_imagem(descricao_foto)

    return {
        "tema": tema,
        "roteiro": roteiro,
        "narracao_limpa": extrair_narracao_limpa(roteiro),
        "avaliacao": avaliacao,
        "historico_revisoes": historico,
        "broll": broll,
        "metadados": metadados,
        "prompt_imagem_gemini": prompt_imagem,
    }


def extrair_narracao_limpa(roteiro):
    """
    Pega só o texto narrado (sem NARRAÇÃO:, sem VISUAL:, sem marcadores
    como [VERIFICAR] ou [ARQUIVO REAL]) - pronto pra colar direto no
    ElevenLabs sem precisar limpar nada na mão.
    """
    trechos = re.findall(
        r"NARRAÇÃO:\s*(.+?)(?=NARRAÇÃO:|VISUAL:|\Z)", roteiro, re.DOTALL
    )
    limpo = []
    for t in trechos:
        t = t.strip()
        t = re.sub(r"\[ARQUIVO REAL\]", "", t)
        t = re.sub(r"\[VERIFICAR\]", "", t)
        t = re.sub(r"\s{2,}", " ", t).strip()
        if t:
            limpo.append(t)
    return "\n\n".join(limpo)


# =========================================================================
# AGENTE 7 - NARRAÇÃO (ElevenLabs) - o que faz soar natural, não "IA slop"
# =========================================================================

def preparar_texto_para_narracao(texto_limpo):
    """
    Ajustes de PONTUAÇÃO (não de conteúdo) que ajudam a fugir do tom
    monótono/robótico típico de narração de IA:
    - <break time="0.6s"/> entre parágrafos - simula a pausa natural de
      alguém respirando/pensando entre uma ideia e a próxima, em vez de
      uma sequência de frases sem fôlego (Multilingual v2 e Flash aceitam
      esse tag de pausa direto no texto; v3 usa tags de emoção em vez
      disso, por isso o pipeline usa Multilingual v2)
    """
    paragrafos = [p.strip() for p in texto_limpo.split("\n\n") if p.strip()]
    return '<break time="0.6s"/>\n\n'.join(paragrafos)


def dividir_em_blocos_narracao(texto_preparado, limite_caracteres=2500):
    """
    Multilingual v2 aceita até 10.000 caracteres por chamada, mas um
    roteiro de 1300+ palavras em português já fica perto disso - divide
    com folga em blocos menores, cortando só em quebra de parágrafo
    (nunca no meio de uma frase), pra depois concatenar o áudio.

    O limite caiu de 8.000 pra 2.500 por causa da cota: a chamada única de
    6.419 caracteres do último log foi recusada INTEIRA por faltarem ~130
    créditos, e o pipeline terminou sem áudio nenhum. Em blocos de 2.500,
    o que cabe na cota é gerado e salvo, e só o resto fica pendente. O
    custo total em créditos é o mesmo (cobrança é por caractere), e a
    costura entre blocos já é tratada por previous_text/next_text.
    """
    separador = '<break time="0.6s"/>\n\n'
    paragrafos = texto_preparado.split(separador)
    blocos = []
    atual = ""
    for p in paragrafos:
        candidato = atual + (separador if atual else "") + p
        if len(candidato) > limite_caracteres and atual:
            blocos.append(atual)
            atual = p
        else:
            atual = candidato
    if atual:
        blocos.append(atual)
    return blocos


def garantir_dicionario_pronuncia():
    """
    Cria (ou reaproveita) o Pronunciation Dictionary do ElevenLabs com as
    regras de REGRAS_PRONUNCIA_ELEVENLABS. Guarda o ID/versão num arquivo
    de cache ao lado do script, pra não recriar o dicionário toda vez que
    o script roda - só recria se o cache não existir ou as regras tiverem
    mudado desde a última vez.
    """
    if not ELEVENLABS_API_KEY or not REGRAS_PRONUNCIA_ELEVENLABS:
        return None

    assinatura_regras = json.dumps(REGRAS_PRONUNCIA_ELEVENLABS, sort_keys=True, ensure_ascii=False)

    if CAMINHO_CACHE_DICIONARIO.exists():
        try:
            with open(CAMINHO_CACHE_DICIONARIO, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            cache = {}
        if cache.get("assinatura") == assinatura_regras:
            # Chave sem permissão pra criar dicionário: já descobrimos isso
            # numa execução anterior, não adianta bater na API de novo (só
            # gera o mesmo aviso 401 em todo run).
            if cache.get("sem_permissao"):
                return None
            if cache.get("dictionary_id") and cache.get("version_id"):
                return cache["dictionary_id"], cache["version_id"]

    regras = [
        {"string_to_replace": termo, "type": "alias", "alias": pronuncia}
        for termo, pronuncia in REGRAS_PRONUNCIA_ELEVENLABS.items()
    ]

    resp = requests.post(
        "https://api.elevenlabs.io/v1/pronunciation-dictionaries/add-from-rules",
        headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
        json={"rules": regras, "name": "Dicionario canal empresas"},
    )
    if resp.status_code != 200:
        if resp.status_code in (401, 403):
            # Chave sem o escopo pronunciation_dictionaries_write - o áudio
            # sai normal, só sem as regras de pronúncia. Marca no cache pra
            # não repetir a tentativa (e o aviso) a cada execução.
            print(
                "    Aviso: esta chave do ElevenLabs não tem permissão "
                "'pronunciation_dictionaries_write' - seguindo sem dicionário "
                "de pronúncia (dá pra liberar isso nas permissões da chave em "
                "elevenlabs.io/app/settings/api-keys)."
            )
            with open(CAMINHO_CACHE_DICIONARIO, "w", encoding="utf-8") as f:
                json.dump({"assinatura": assinatura_regras, "sem_permissao": True}, f)
        else:
            print(
                f"    Aviso: falha ao criar dicionário de pronúncia "
                f"({resp.status_code}) - seguindo sem ele: {resp.text[:200]}"
            )
        return None

    dados = resp.json()
    if "id" not in dados or "version_id" not in dados:
        print(f"    Aviso: resposta inesperada da API de dicionário - {dados}")
        return None

    dictionary_id = dados["id"]
    version_id = dados["version_id"]

    with open(CAMINHO_CACHE_DICIONARIO, "w", encoding="utf-8") as f:
        json.dump(
            {
                "assinatura": assinatura_regras,
                "dictionary_id": dictionary_id,
                "version_id": version_id,
            },
            f,
        )

    print(f"    (dicionário de pronúncia criado: {len(regras)} regra(s))")
    return dictionary_id, version_id


def consultar_cota_elevenlabs():
    """
    Pergunta pra própria ElevenLabs quantos créditos (caracteres) ainda
    restam no ciclo atual, ANTES de mandar texto. Sem isso, a única forma
    de descobrir que a cota acabou é a chamada ser recusada inteira - foi
    o que aconteceu no último run: 6.419 caracteres pedidos, 3.094
    créditos necessários, 2.963 disponíveis, e o pipeline terminou sem
    áudio nenhum.

    Retorna (usados, limite) ou None se não deu pra consultar (nesse caso
    o pipeline segue e simplesmente tenta gerar).
    """
    try:
        resp = requests.get(
            "https://api.elevenlabs.io/v1/user/subscription",
            headers={"xi-api-key": ELEVENLABS_API_KEY},
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        dados = resp.json()
        usados = dados.get("character_count")
        limite = dados.get("character_limit")
        if usados is None or limite is None:
            return None
        return usados, limite
    except Exception:
        return None


def _salvar_narracao_pendente(blocos_pendentes, caminho_saida_mp3):
    """
    Salva num .txt o pedaço da narração que NÃO virou áudio (cota acabou
    ou a API recusou), já sem as tags de pausa, pronto pra colar no site
    da ElevenLabs depois que a cota renovar.
    """
    texto = "\n\n".join(blocos_pendentes)
    texto = re.sub(r"<break[^>]*/>", "", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    caminho = caminho_saida_mp3.with_name(
        caminho_saida_mp3.stem + "_narracao_restante.txt"
    )
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)
    return caminho, len(texto)


def gerar_audio_elevenlabs(texto_narracao_limpo, caminho_saida_mp3):
    """
    Gera o arquivo de áudio final via ElevenLabs. Retorna o caminho salvo
    (mesmo que parcial), ou None se pulou (sem chave configurada) ou não
    conseguiu gerar nem o primeiro bloco - o resto do pipeline continua
    normalmente de qualquer jeito.

    Usa Request Stitching (previous_text/next_text) quando o roteiro
    precisa ser dividido em mais de um bloco - sem isso, cada bloco é
    tratado como uma frase isolada e ganha uma "cadência final" (queda de
    tom no fim) mesmo quando o pensamento continua no próximo bloco.

    Quando a cota não dá pra narração inteira, gera o que couber, salva
    esse áudio parcial e escreve o texto restante num .txt - antes, um
    único bloco grande era recusado por completo e você ficava sem nada.
    """
    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        print(
            "    Aviso: ELEVENLABS_API_KEY ou ELEVENLABS_VOICE_ID não "
            "configurados no .env - pulando geração de áudio."
        )
        return None

    texto_preparado = preparar_texto_para_narracao(texto_narracao_limpo)
    blocos = dividir_em_blocos_narracao(texto_preparado)
    custo_total = sum(len(bloco) for bloco in blocos)

    creditos_restantes = None
    cota = consultar_cota_elevenlabs()
    if cota:
        usados, limite = cota
        creditos_restantes = max(limite - usados, 0)
        print(
            f"    Cota ElevenLabs: {creditos_restantes} crédito(s) de "
            f"{limite} ainda disponíveis; esta narração custa ~{custo_total}."
        )
        if custo_total > creditos_restantes:
            print(
                "    Atenção: a cota não cobre a narração inteira - vou gerar "
                "só o que couber e salvar o restante do texto num .txt pra "
                "você terminar quando a cota renovar."
            )
    else:
        print(
            "    (não consegui consultar a cota do ElevenLabs - seguindo "
            "e tentando gerar normalmente)"
        )

    dicionario = garantir_dicionario_pronuncia()

    # Quantos caracteres de contexto mandar como previous_text/next_text -
    # não precisa do bloco inteiro, só o suficiente pra dar pista de tom
    JANELA_CONTEXTO = 500

    audio_completo = b""
    gasto = 0
    indice_parada = None  # primeiro bloco que NÃO entrou no áudio

    for i, bloco in enumerate(blocos, 1):
        if creditos_restantes is not None and gasto + len(bloco) > creditos_restantes:
            print(
                f"    Cota esgotada antes do bloco {i}/{len(blocos)} - "
                "parando aqui e guardando o resto do texto."
            )
            indice_parada = i - 1
            break

        print(f"    Gerando áudio - bloco {i}/{len(blocos)} ({len(bloco)} caracteres)...")

        corpo = {
            "text": bloco,
            "model_id": ELEVENLABS_MODEL,
            # "on" força normalizar número/data/moeda sempre (em vez de
            # deixar o modelo decidir) - resolve pronúncia estranha de
            # "R$ 1 bilhão", "72%", anos, etc.
            "apply_text_normalization": "on",
            # Ajuda a desambiguar quando o texto tem palavra estrangeira
            # misturada (cashback, e-commerce) - evita o normalizador
            # aplicar regra errada por achar que o texto é outro idioma
            "language_code": "pt",
            "voice_settings": {
                # Ajustado com base em análise real do áudio: o tom ficava
                # quase reto no fim de frase (só ~2% de queda de pitch em
                # média, quando fala humana natural desce o tom pra
                # sinalizar fim de pensamento) - baixar stability e subir
                # style dá mais variação de entonação pro modelo aplicar
                # essa descida sozinho. Se ainda soar reto, desça mais
                # stability (até uns 0.3); se ficar instável/errático
                # demais, suba de novo.
                "stability": 0.35,
                "similarity_boost": 0.75,
                "style": 0.3,
                "use_speaker_boost": True,
            },
        }
        if dicionario:
            corpo["pronunciation_dictionary_locators"] = [
                {"pronunciation_dictionary_id": dicionario[0], "version_id": dicionario[1]}
            ]
        if i > 1:
            corpo["previous_text"] = blocos[i - 2][-JANELA_CONTEXTO:]
        if i < len(blocos):
            corpo["next_text"] = blocos[i][:JANELA_CONTEXTO]

        try:
            resp = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                },
                json=corpo,
                timeout=300,
            )
        except Exception as e:
            print(f"    Aviso: falha de rede no bloco {i} ({type(e).__name__}).")
            indice_parada = i - 1
            break

        if resp.status_code != 200:
            if "quota_exceeded" in resp.text or resp.status_code in (402, 429):
                print(
                    f"    Cota do ElevenLabs acabou no bloco {i}/{len(blocos)} - "
                    "guardando o que já foi gerado e o texto que falta."
                )
            else:
                print(
                    f"    Aviso: ElevenLabs retornou erro {resp.status_code} no "
                    f"bloco {i} - {resp.text[:200]}"
                )
            indice_parada = i - 1
            break

        audio_completo += resp.content
        gasto += len(bloco)
    else:
        indice_parada = len(blocos)

    blocos_pendentes = blocos[indice_parada:]

    if not audio_completo:
        caminho_pendente, faltando = _salvar_narracao_pendente(
            blocos_pendentes, caminho_saida_mp3
        )
        print(
            f"    Nenhum áudio foi gerado. A narração inteira ({faltando} "
            f"caracteres) ficou em: {caminho_pendente}"
        )
        return None

    if blocos_pendentes:
        caminho_final = caminho_saida_mp3.with_name(
            caminho_saida_mp3.stem + "_parcial" + caminho_saida_mp3.suffix
        )
    else:
        caminho_final = caminho_saida_mp3

    with open(caminho_final, "wb") as f:
        f.write(audio_completo)

    if blocos_pendentes:
        caminho_pendente, faltando = _salvar_narracao_pendente(
            blocos_pendentes, caminho_saida_mp3
        )
        print(
            f"    Áudio PARCIAL salvo em: {caminho_final} "
            f"({indice_parada} de {len(blocos)} blocos)"
        )
        print(
            f"    Faltam {faltando} caracteres de narração - texto pronto pra "
            f"colar no ElevenLabs em: {caminho_pendente}"
        )
    else:
        print(f"    Áudio salvo em: {caminho_final}")

    return str(caminho_final)


def montar_relatorio_txt(resultado):
    """Monta uma versão em texto puro do resultado, formatada pra leitura
    fácil no Bloco de Notas (ou qualquer editor) - sem chaves, aspas
    escapadas ou \\n literal do JSON."""
    partes = []
    partes.append("=" * 70)
    partes.append(f"TEMA: {resultado['tema']}")
    partes.append("=" * 70)

    partes.append("\n\n### ROTEIRO (com marcações, pra revisar) ###\n")
    partes.append(resultado["roteiro"])

    partes.append("\n\n" + "=" * 70)
    partes.append(
        "### NARRAÇÃO LIMPA - PRONTA PRA COLAR NO ELEVENLABS ###\n"
        "IMPORTANTE: revise os trechos marcados [VERIFICAR] no roteiro "
        "acima ANTES de gravar - essa versão abaixo já vem sem essas "
        "marcações, então é sua última chance de conferir os fatos.\n"
    )
    partes.append(extrair_narracao_limpa(resultado["roteiro"]))

    partes.append("\n\n" + "=" * 70)
    partes.append("### AVALIAÇÃO DO CRÍTICO (última rodada) ###\n")
    partes.append(resultado["avaliacao"])

    if resultado.get("historico_revisoes"):
        partes.append("\n\n" + "=" * 70)
        partes.append("### HISTÓRICO DE TODAS AS TENTATIVAS (o que foi reprovado) ###\n")
        for item in resultado["historico_revisoes"]:
            partes.append(f"Tentativa {item['tentativa']}: {item['veredito'].upper()}")
            if item["veredito"] == "reprovado":
                partes.append(f"  Motivo: {item['mudancas_pedidas']}")
            partes.append("")

    partes.append("\n\n" + "=" * 70)
    partes.append("### TÍTULO, THUMBNAIL, DESCRIÇÃO E TAGS ###\n")
    partes.append(resultado["metadados"])

    partes.append("\n\n" + "=" * 70)
    partes.append("### PROMPT PRA EDITAR SUA FOTO NO GEMINI ###\n")
    partes.append(resultado["prompt_imagem_gemini"])

    partes.append("\n\n" + "=" * 70)
    partes.append("### B-ROLL ENCONTRADO POR TRECHO ###\n")
    for termo, dados in resultado["broll"].items():
        partes.append(f"- {termo}")
        if isinstance(dados, dict) and dados.get("tipo") == "arquivo_real_necessario":
            partes.append("  (precisa de foto/vídeo real de arquivo, não de banco de stock)")
        elif dados:
            for item in dados:
                partes.append(f"  {item['preview']}")
        else:
            partes.append("  (nenhum resultado encontrado)")

    return "\n".join(partes)


if __name__ == "__main__":
    pasta_saidas = PASTA_DO_SCRIPT / "saidas"
    pasta_saidas.mkdir(exist_ok=True)

    modo = input(
        "1 - Gerar vídeo novo do zero\n"
        "2 - Usar um roteiro já pronto (JSON salvo antes) - útil pra "
        "testar só o áudio ou reaproveitar um roteiro\n"
        "Escolha (1/2), ou Enter pra gerar novo: "
    ).strip()

    resultado = None
    carimbo = None

    if modo == "2":
        arquivos_json = sorted(
            pasta_saidas.glob("video_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not arquivos_json:
            print(f"Nenhum JSON encontrado em {pasta_saidas} - gerando vídeo novo em vez disso.\n")
        else:
            print("\nRoteiros salvos encontrados (mais recente primeiro):")
            for i, arq in enumerate(arquivos_json, 1):
                print(f" {i}. {arq.name}")
            escolha = input(
                f"\nEscolha o número (1-{len(arquivos_json)}), ou Enter pra "
                "usar o mais recente: "
            ).strip()
            if escolha.isdigit() and 1 <= int(escolha) <= len(arquivos_json):
                caminho_escolhido = arquivos_json[int(escolha) - 1]
            else:
                caminho_escolhido = arquivos_json[0]

            print(f"Carregando: {caminho_escolhido.name}\n")
            with open(caminho_escolhido, "r", encoding="utf-8") as f:
                resultado = json.load(f)

            # JSONs salvos antes do agente de áudio existir não têm essa
            # chave - calcula na hora se estiver faltando
            if "narracao_limpa" not in resultado:
                resultado["narracao_limpa"] = extrair_narracao_limpa(resultado["roteiro"])

            # Reaproveita o mesmo carimbo do arquivo carregado, pra o áudio
            # (e o json/txt, se algo mudar) ficarem juntos com o mesmo nome
            carimbo = caminho_escolhido.stem.replace("video_", "")

    if resultado is None:
        print("Buscando temas em alta (notícia)...")
        temas_noticia = pesquisar_temas_em_alta()
        print("Temas de notícia encontrados:")
        for t in temas_noticia:
            print(" -", t)

        print("\nBuscando vídeos de maior sucesso dos canais de referência...")
        titulos_referencia = buscar_referencias()
        if titulos_referencia:
            print(f"  {len(titulos_referencia)} títulos de referência encontrados.")
            print("Analisando padrão e gerando temas inspirados...")
            analise, temas_inspirados = gerar_temas_por_referencia(titulos_referencia)
            print("Temas inspirados nas referências:")
            for t in temas_inspirados:
                print(" -", t)
        else:
            print("  YOUTUBE_API_KEY não configurada ou nenhum resultado - "
                  "pulando o agente de referência.")
            temas_inspirados = []

        # Junta as duas fontes - notícia traz atualidade, referência traz
        # temas evergreen com padrão comprovado de sucesso
        todos_temas = temas_inspirados + temas_noticia
        if not todos_temas:
            todos_temas = ["Como a BYD ficou tão grande"]

        print("\nTodos os temas candidatos:")
        for i, t in enumerate(todos_temas, 1):
            print(f" {i}. {t}")

        entrada = input(
            f"\nEscolha um tema (1-{len(todos_temas)}), digite o SEU próprio "
            "tema, ou pressione Enter pra usar o nº 1: "
        ).strip()

        if not entrada:
            tema_escolhido = todos_temas[0]
        elif entrada.isdigit() and 1 <= int(entrada) <= len(todos_temas):
            tema_escolhido = todos_temas[int(entrada) - 1]
        else:
            tema_escolhido = entrada  # você não gostou de nenhum - digitou o seu

        print(f"\nUsando tema: {tema_escolhido}\n")

        resultado = gerar_video_completo(tema_escolhido)
        carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Salva numa pasta "saidas" ao lado do script (não depende de onde o
    # comando foi rodado). Se veio de um JSON carregado, reaproveita o
    # mesmo nome; se é vídeo novo, usa o carimbo gerado agora.
    caminho_json = pasta_saidas / f"video_{carimbo}.json"
    caminho_txt = pasta_saidas / f"video_{carimbo}.txt"

    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    with open(caminho_txt, "w", encoding="utf-8") as f:
        f.write(montar_relatorio_txt(resultado))

    print("Gerando áudio da narração (ElevenLabs)...")
    caminho_mp3 = pasta_saidas / f"video_{carimbo}.mp3"
    audio_gerado = gerar_audio_elevenlabs(resultado["narracao_limpa"], caminho_mp3)

    print("Baixando clipes de b-roll...")
    pasta_broll = pasta_saidas / f"video_{carimbo}_broll"
    baixados, pulados = baixar_broll(resultado["broll"], pasta_broll)

    print("\nConcluído!")
    print(f"  Texto legível (abra no Bloco de Notas): {caminho_txt}")
    print(f"  Dados completos (JSON):                 {caminho_json}")
    if audio_gerado:
        print(f"  Áudio da narração:                      {audio_gerado}")
    if baixados:
        print(f"  Clipes de b-roll ({len(baixados)}):{' ' * 14}         {pasta_broll}")
    if pulados:
        print(f"  Trechos sem clipe baixado ({len(pulados)}) - veja o .txt pra detalhes")
