"""
Pipeline de criação de roteiros para YouTube - nicho empresas/administração
============================================================================

4 AGENTES:
0. Pesquisador de fatos -> ANTES de escrever, levanta material real sobre o
    tema (Wikipédia + Wikidata + manchetes datadas do Google News) e passa
    esse dossiê pro roteirista e pro crítico. Sem chave de API, com cache em
    disco. Existe porque o roteirista não consulta nada: tudo que ele
    escreve sai da memória do modelo, e memória de modelo inventa com
    confiança (um roteiro aprovado já descreveu relatório, vídeo viral e
    reunião de diretoria que nunca existiram). Desligue em
    USAR_PESQUISA_DE_FATOS se estiver sem internet.
1. Pesquisador  -> função pesquisar_temas_em_alta() continua no código, mas
    NÃO é chamada em lugar nenhum do fluxo interativo - manchete de jornal
    quase nunca vira tema bom aqui (vem com nome do veículo colado, é
    notícia do dia, não evergreen), e na prática o tema sempre acaba
    vindo do agente de Referência (1B) mesmo. Se um dia quiser usá-la,
    é só chamar a função e juntar o resultado a todos_temas no __main__.
1B. Referência  -> busca os vídeos mais vistos de canais de referência do
    nicho (Elementar) via API do YouTube, e
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

TAMANHO DO ROTEIRO - por que a escrita é em blocos:
    Pedindo o roteiro inteiro numa chamada, o modelo local devolveu 532 e
    361 palavras em dois runs reais, contra o alvo de 1270-1620 - e o
    passe de expansão, que existia pra corrigir isso, recuperou 9 e 1
    palavra. Modelo pequeno não sustenta texto longo num turno só. Agora
    são seis chamadas de 60 a 350 palavras cada (ESCREVER_POR_BLOCOS), com
    o alvo pedido como TOPO da faixa e retentativa do bloco que vier
    abaixo do mínimo. A contagem e a duração estimada aparecem a cada
    bloco, então dá pra ver o roteiro crescendo em vez de descobrir no
    fim que saiu curto.

LOOP DE REVISÃO (roteirista <-> crítico) - por que ele termina:
    O loop já travou em roteiro bom por motivo que o roteirista não tinha
    como resolver. Quatro regras garantem que ele converge:
    a) o que é mecânico, o CÓDIGO faz - marcar_verificar_automatico()
       coloca [VERIFICAR] em todo número específico antes da avaliação
       (era 88% das reprovações, e nunca dependeu de julgamento);
    b) roteiro curto é EXPANDIDO antes de ser avaliado, não depois - um
       esqueleto de 300 palavras seria reprovado por falta de bloco em
       todas as tentativas, sem chance de melhorar;
    c) só reprova o roteiro o pedido que o roteirista consegue executar -
       sugestão ("considere...") e pedido de pesquisa ("verifique a
       veracidade", que ele não tem como fazer) não bloqueiam mais;
    d) se o crítico repete o MESMO pedido 3 vezes, o loop para e entrega
       a melhor versão do run com a pendência anotada, em vez de queimar
       tentativa e devolver a última versão só por ser a última.

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

# False = Ollama 100% local (sem cota, sem internet, mas modelo bem mais
# fraco e mais lento). True = Groq na nuvem (modelo forte, mas depende de
# cota diária). Dá pra alternar a qualquer momento mudando só esta linha.
#
# ATENÇÃO ao voltar pro local: nos testes anteriores desta conversa, o
# modelo de 7B mostrou limite real pra este tipo de tarefa - roteiro
# saindo curto mesmo com instrução explícita de tamanho, e crítico
# repetindo reprovação genérica sem avaliar o conteúdo de verdade. Foi
# exatamente por isso que migramos pra nuvem. Como o pipeline ganhou
# várias travas desde então (validação de roteiro vazio, escalação após
# 2 reprovações, passe de expansão), pode ser que agora renda melhor -
# mas não espere a mesma qualidade do gpt-oss-120b.
USAR_NUVEM = False  # True = usa Groq | False = volta pro Ollama 100% local

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

# O Ollama expõe uma API compatível com OpenAI em /v1, mas NÃO usamos
# ela: aquele endpoint ignora o num_ctx e trunca o prompt em 4096 tokens
# silenciosamente (ver comentário grande em _chamar_ollama_nativo). Toda
# chamada local vai pelo endpoint nativo /api/chat, via requests.
OLLAMA_BASE_URL = "http://localhost:11434"

# Janela de contexto pedida ao Ollama. O padrão do daemon (2048-4096) NÃO
# cabe os prompts deste pipeline - o do crítico embute o roteiro inteiro e
# passa de 8.000 tokens. 16384 dá folga.
# CUSTO EM VRAM: contexto maior consome mais memória de vídeo. Na sua RTX
# 3050 de 6GB, um modelo 7B em Q4 com 16k de contexto deve caber, mas é
# apertado - se o Ollama começar a jogar camadas pra CPU (fica MUITO mais
# lento) ou der erro de memória, baixe pra 12288 ou 8192.
OLLAMA_NUM_CTX = 16384

# Modelo local rodando na CPU/GPU da sua máquina é bem mais lento que a
# nuvem: um roteiro longo pode levar vários minutos. Timeout generoso pra
# não cortar no meio de uma geração legítima.
OLLAMA_TIMEOUT_S = 900

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
#
# RECOMENDAÇÕES DE VOZ PESQUISADAS (confira e ouça antes de decidir - gosto
# de voz é subjetivo, isso é só um ponto de partida):
# - "Dan" (voice_id: BHr135B5EUBtaWheVj8S) - recomendação OFICIAL da
#   própria ElevenLabs especificamente pro gênero documentário/investigação
#   (blog oficial deles). Voz em inglês original, mas funciona em português
#   via Multilingual v2/Flash - teste o sotaque antes de decidir.
# - Outras vozes NATIVAS em português brasileiro que apareceram como boas
#   pra narração/documentário (procure pelo nome na Voice Library e copie
#   o voice_id de lá - não colei os IDs aqui porque a fonte que listei
#   tinha nome e ID desalinhados, e ID errado = voz errada gastando
#   crédito): "Adriano - Narrator" (voz grave, storytelling),
#   "Eduardo Hubi" (voz calma, passa credibilidade),
#   "Marcelo Costa_Brasileiro", "Victor Power - Ebooks".
#
# ESCOLHIDA: "Cassio Cruz" - voz masculina brasileira grave, descrita como
# boa pra narração de documentário. O ID abaixo foi conferido por você
# direto no painel da ElevenLabs (não é chute meu). Continua podendo ser
# sobrescrito pelo .env se quiser testar outra voz sem mexer no código.
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "TbxkrwWBTzuT49yXcfss")

# Escolhi o Flash (mais barato, $0,05/1k caracteres - metade do preço da
# Multilingual v2) por pedido explícito, sabendo do trade-off real: toda
# fonte que pesquisei (doc oficial, reviews independentes) concorda que a
# Multilingual v2 tem prosódia mais refinada em narração longa - "a
# diferença é audível, principalmente em passagens longas, no ritmo e na
# ênfase" foi a frase exata de uma delas. Compensei subindo um pouco mais
# o "style" no voice_settings abaixo pra tentar recuperar parte dessa
# expressividade, mas não testei se compensa de verdade - ouça o resultado
# e, se sentir mais robótico que antes, troque essa linha de volta pra
# "eleven_multilingual_v2" (custa o dobro, mas foi o que testamos e
# funcionou na análise de pitch anterior).
ELEVENLABS_MODEL = "eleven_flash_v2_5"

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

# Arquivo que acumula, entre TODAS as execuções (não só a atual), quais
# problemas o crítico mais aponta - usado pra reforçar automaticamente
# esses pontos específicos no prompt do roteirista. Não é "aprendizado de
# máquina" de verdade (o modelo não é retreinado) - é um contador de
# padrões de erro que se repetem, alimentando o próprio prompt sozinho.
CAMINHO_ESTATISTICAS_APRENDIZADO = PASTA_DO_SCRIPT / ".estatisticas_aprendizado.json"

# Campos do template de avaliação que indicam um problema real quando
# preenchidos (o valor "vazio" de cada um varia - por isso a checagem
# fica em _campo_indica_problema, não aqui)
# =========================================================================
# B-ROLL ILUSTRADO (agente 4B) - imagem gerada por IA
# =========================================================================
# True = trechos específicos da história ganham ilustração gerada; False =
# tudo vem do Pexels, como antes.
USAR_BROLL_IA = True

# "pollinations" é o padrão por ser GRATUITO e não exigir chave nenhuma.
# "huggingface" também é gratuito, mas precisa de um token (grátis) no
# .env e tem fila. Provedor pago com referência de imagem (Ideogram,
# gpt-image-1, Imagen) entra aqui depois, na mesma interface - ver
# _PROVEDORES_DE_IMAGEM.
PROVEDOR_IMAGEM = "pollinations"
POLLINATIONS_MODELO = "flux"
HUGGINGFACE_MODELO_IMAGEM = "black-forest-labs/FLUX.1-schnell"
HUGGINGFACE_TOKEN = os.getenv("HUGGINGFACE_TOKEN", "")

# Teto de imagens por vídeo. Com provedor gratuito o custo é tempo e
# limite de uso, não dinheiro - mas o teto continua valendo pra não
# transformar um vídeo inteiro em slideshow de imagem parada.
MAX_AI_IMAGES_PER_VIDEO = 12

# Proporção máxima de trechos ilustrados. É TETO, não cota: nunca empurra
# um trecho pra IA só pra bater a porcentagem.
TETO_PROPORCAO_IA = 0.4

# Resolução da geração. Maior que o frame final de propósito: sobra de
# pixel é espaço de zoom no Ken Burns, que você aplica na edição. O
# provedor pode devolver menos que isso - nenhum gerador entrega 4K hoje.
IMAGEM_IA_LARGURA = 2048
IMAGEM_IA_ALTURA = 1152
IMAGEM_IA_TIMEOUT_S = 180

# QUEM É O PERSONAGEM DO CANAL.
#
# Preenchido = esse personagem em TODOS os vídeos, sempre a mesma roupa.
# É o modo "mascote do canal": o espectador reconhece o sujeito de um
# vídeo pro outro, e economiza uma chamada ao LLM por vídeo.
#
# Vazio ("") = o LLM escolhe a roupa por vídeo, a partir do roteiro (num
# vídeo sobre uma lojinha ele viria de avental; num sobre uma diretoria,
# de terno). Mais fiel a cada história, mas o personagem muda de cara
# entre vídeos.
#
# O QUE NUNCA MUDA DENTRO DO MESMO VÍDEO é a roupa: sem imagem de
# referência, ela é a ÚNICA âncora de consistência que sobra - a cabeça é
# um círculo sem rosto, não há traço facial pra reconhecer. O que varia de
# cena pra cena é gesto, expressão, cenário e objetos, que é exatamente o
# que descrever_cena_para_imagem() extrai do roteiro.
# Padrão: vazia - o personagem se veste conforme a história de cada vídeo.
# Pra fixar um personagem só pro canal inteiro, escreva a descrição aqui,
# por exemplo:
#   FICHA_PERSONAGEM_FIXA = (
#       "the same recurring character in every scene: bald round head, "
#       "dark navy business suit, white dress shirt, thin dark tie"
#   )
FICHA_PERSONAGEM_FIXA = ""

# Rede de segurança pro caso de a ficha automática não sair (LLM fora do ar
# ou resposta inutilizável). NÃO pode ser derivada de FICHA_PERSONAGEM_FIXA:
# com ela vazia, o padrão também ficaria vazio e a imagem sairia sem
# personagem nenhum - a descrição da cena viraria um cenário vazio.
FICHA_PERSONAGEM_PADRAO = (
    "the same recurring character in every scene: bald round head, plain "
    "grey shirt, thin black stick arms"
)

# =========================================================================
# PESQUISA DE FATOS (agente 0) - o que o roteirista lê antes de escrever
# =========================================================================
# True = antes de escrever, o pipeline levanta material real sobre o tema
# (Wikipédia + Wikidata + manchetes) e entrega isso pro roteirista. Custa
# 1 chamada curta ao LLM (pra decidir o que pesquisar) + alguns segundos
# de internet, e não usa chave de API nenhuma. False = volta ao
# comportamento antigo, em que tudo sai da memória do modelo.
USAR_PESQUISA_DE_FATOS = True

PESQUISA_TIMEOUT_S = 12          # por requisição; fonte lenta é pulada
PESQUISA_MAX_CHARS_DOSSIE = 6000  # teto do dossiê no prompt da 1ª escrita
PESQUISA_MAX_CHARS_DOSSIE_CURTO = 2000  # nas revisões e no crítico, onde o
                                        # prompt já carrega o roteiro inteiro
PESQUISA_MAX_MANCHETES = 10
PESQUISA_VALIDADE_CACHE_DIAS = 7

# O dossiê fica em cache porque "refazer só o roteiro" e cada tentativa do
# loop usariam exatamente o mesmo material.
PASTA_CACHE_PESQUISA = PASTA_DO_SCRIPT / ".cache_pesquisa"

_CAMPOS_PROBLEMA_APRENDIZADO = (
    "MINI-GANCHOS FALTANDO",
    "JARGÃO NÃO EXPLICADO",
    "VISUAIS PROBLEMÁTICOS",
    "RÓTULO DE INSTRUÇÃO VAZADO",
    "NÚMEROS SEM VERIFICAR",
    "PESSOA INVENTADA",
    "EVENTO SEM VERIFICAR",
    "EMPRESA IDENTIFICÁVEL MAS NÃO NOMEADA",
)

# =========================================================================
# ESQUEMA "ESCREVER EM INGLÊS" - roteirista e crítico trabalham em inglês
# (modelos costumam seguir regra complexa melhor em inglês do que em
# português), e só no final um agente de tradução converte pra português
# falado natural. Os RÓTULOS de estrutura (NARRAÇÃO:, VISUAL:, [VERIFICAR],
# [ARQUIVO REAL], nomes dos campos do crítico) continuam SEMPRE em
# português, em inglês ou não - isso é só uma marcação fixa que o código
# procura por regex, não precisa mudar de idioma junto com o conteúdo.
# Isso mantém toda a extração de b-roll/palavras/veredito funcionando
# sem alteração nenhuma, o único agente novo é o de tradução no final.
# =========================================================================
GERAR_EM_INGLES = True  # False = volta pro fluxo 100% em português direto

# True = o roteiro é escrito em seis chamadas pequenas (uma por bloco) em
# vez de uma grande. Medido em dois runs reais com qwen2.5:7b, a chamada
# única devolveu 532 e 361 palavras contra um alvo de 1270-1620, e o passe
# de expansão recuperou 9 e 1 palavra. Bloco de 300 palavras o modelo
# entrega; roteiro inteiro, não. False volta pro comportamento antigo (faz
# sentido com modelo grande na nuvem, que aguenta o texto todo de uma vez).
ESCREVER_POR_BLOCOS = True

# Canais de referência do nicho pra puxar inspiração dos vídeos que mais
# renderam. Handles confirmados (conferidos por busca, não chutados):
# - Elementar: documentário narrativo de empresas/negócios (o mais próximo
#   do estilo do canal)
# - primorico: Primo Rico (Thiago Nigro), finanças/investimentos
# - NerdsdeNegocios: Peter Jordan, maior canal de empreendedorismo do Brasil
# Use o handle exatamente como aparece na URL do canal (youtube.com/@handle).
CANAIS_REFERENCIA = ["Elementar"]


# =========================================================================
# PROMPTS (os que já validamos juntos)
# =========================================================================

ROTEIRO_PROMPT = """Você é um roteirista de vídeos de YouTube sobre empresas e administração,
estilo documentário narrativo (referência: Elementar. Canal faceless, narrado em primeira pessoa. Siga as instruções
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
   ano de fundação de empresa famosa)? IMPORTANTE: um [VERIFICAR] em
   qualquer ponto próximo da MESMA linha NARRAÇÃO já marca o número -
   não exija um marcador colado em cada algarismo, e não liste como
   problema um número que já tem [VERIFICAR] na linha. Liste TODOS os
   que realmente não tiverem, não só os 2-3 primeiros que achar. Se houver 3 ou mais números
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

EVENTO SEM VERIFICAR: [liste TODO EVENTO narrativo apresentado como fato
que esteja sem [VERIFICAR] e não seja de conhecimento público amplo -
processo, investigação, relatório de órgão de defesa do consumidor, vídeo
viral, coletiva de imprensa, reunião de diretoria, decisão interna,
mudança de política. Isto NÃO é sobre número (esse é o campo acima) - é
sobre a HISTÓRIA EM SI possivelmente ser inventada. Falha real que já
aconteceu: um roteiro descreveu um relatório de defesa do consumidor, um
vídeo viral no TikTok e um debate interno da diretoria, todos com datas
confiantes, nenhum marcado - como os números estavam todos marcados, foi
aprovado, e o ENREDO INTEIRO era ficção não verificada sobre uma empresa
real. Marque especialmente qualquer trecho que impute MÁ-FÉ DELIBERADA
(mirar usuários silenciosamente, esconder taxas de propósito, refinar
algoritmos pra explorar) - isso é acusação, não descrição, e sempre precisa
de [VERIFICAR]. Ou escreva "Nenhum encontrado"]

EMPRESA IDENTIFICÁVEL MAS NÃO NOMEADA: [ATENÇÃO - a INTRODUÇÃO não conta
aqui: ela esconde o nome da empresa DE PROPÓSITO, é o gancho do vídeo e
regra fixa deste canal. NUNCA peça pra nomear a empresa na introdução, na
abertura ou nas primeiras linhas - esse pedido contraria a regra que o
roteirista é obrigado a seguir, então ele nunca vai poder atender, e o
roteiro fica preso reprovando pra sempre. O que se avalia neste campo é o
CORPO do texto (backstory, miolo, conclusão): lá o roteiro tem que nomear
a empresa real. Se ele evita o nome mas acumula detalhes que
identificam uma empresa específica mesmo assim (ano de fundação + setor +
rodada de captação + data do IPO + avaliação), isso é o pior dos dois
mundos: não tem a proteção de discussão genérica e ainda quebra a regra de
nomear. Cite os detalhes identificadores se isso acontecer, ou escreva
"Nenhum encontrado"]

CHANCE DE RETENÇÃO: [baixa / média / alta]

MUDANÇAS OBRIGATÓRIAS: [lista objetiva do que mudar, só o essencial - se
houver qualquer item nos campos "RÓTULO DE INSTRUÇÃO VAZADO", "NÚMEROS
SEM VERIFICAR", "PESSOA INVENTADA", "EVENTO SEM VERIFICAR" ou "EMPRESA
IDENTIFICÁVEL MAS NÃO NOMEADA", ele SEMPRE entra aqui como
obrigatório, sem exceção. Se não houver nada obrigatório, escreva "Nenhuma".

COMO ESCREVER CADA ITEM (regra dura - quem lê isto é o roteirista, que só
sabe mexer no texto e não tem como pesquisar nada):
- Um item por linha, começando com VERBO NO IMPERATIVO (Adicione, Remova,
  Troque, Reescreva, Nomeie) e dizendo ONDE mexer.
- PROIBIDO copiar pra cá uma lista solta de dados. Escrever só
  "R$ 2,5 bilhões, 24%, 2015, 2019" NÃO é uma mudança - o roteirista
  recebe isso sem saber o que fazer e devolve o mesmo roteiro. A forma
  certa é: "Adicione [VERIFICAR] ao lado de R$ 2,5 bilhões, 24% e 2019
  nas linhas NARRAÇÃO em que aparecem".
- PROIBIDO pedir "verifique a veracidade", "confirme a fonte" ou
  "pesquise": o roteirista não tem acesso a fonte nenhuma. A única ação
  equivalente que ele consegue executar é ADICIONAR [VERIFICAR] no
  trecho - peça isso.
- PROIBIDO escrever sugestão aqui ("considere", "seria bom", "poderia").
  Este campo é só do que REPROVA o roteiro. Sugestão vai nos campos de
  cima, não aqui.
- Antes de pedir [VERIFICAR] num número, CONFIRA se ele já não está
  marcado na linha. O pipeline marca os números automaticamente antes de
  você ver o roteiro, então pedir de novo é pedir algo que já está feito -
  o roteirista não tem o que fazer e a rodada inteira é perdida.
- PROIBIDO pedir pra nomear a empresa na introdução/abertura/primeiras
  linhas. A introdução esconde o nome de propósito (é o gancho). Se o
  problema é o corpo do texto não nomear, diga isso: "Nomeie a empresa no
  backstory/miolo".
- Se o item já foi pedido numa rodada anterior e o roteirista atendeu,
  NÃO repita. Repetir o mesmo pedido trava o roteiro no mesmo lugar.]

VEREDITO: [escreva exatamente a palavra APROVADO se não houver nenhuma
mudança obrigatória, ou exatamente a palavra REPROVADO se houver pelo menos
uma mudança obrigatória. Escreva só essa palavra nesta linha, em maiúsculas,
nada mais.]
"""

# =========================================================================
# VERSÕES EM INGLÊS (roteirista e crítico) - mesmas regras do par acima,
# mas escritas em inglês pra aproveitar o fato de que modelos costumam
# seguir instrução complexa com mais precisão nesse idioma. Os RÓTULOS de
# estrutura ficam em português DE PROPÓSITO (NARRAÇÃO:, VISUAL:,
# [VERIFICAR], [ARQUIVO REAL], e os nomes de campo do crítico) - é só uma
# marcação fixa que o código busca por regex, funciona igual em qualquer
# idioma ao redor dela, e assim TODA a extração (b-roll, contagem de
# palavra, veredito, aprendizado) continua funcionando sem nenhuma
# alteração, seja o conteúdo em português ou em inglês.
# =========================================================================

ROTEIRO_PROMPT_EN = """You are a YouTube scriptwriter for a business/management channel, narrative
documentary style (reference: Elementar). Faceless channel, narrated in
first person PLURAL - the guided-tour voice: "repare no que acontece
agora", "vamos aos números", "olha o tamanho disso", "agora segura essa".
Use it deliberately, roughly once per block, to steer the viewer's
attention at a turn in the story - NOT as decoration sprinkled at random.

Two hard limits on this voice. First, NEVER first person SINGULAR: no "eu
descobri", "eu fui atrás dos documentos", "na minha opinião". The
narration voice is synthetic and the writer did no reporting - claiming
personal investigation is a lie, and it turns every statement into a
personal allegation by the channel owner. Second, the guiding voice never
carries a factual claim by itself: "vamos aos números" is fine, "eu vi os
números" is not.

Follow the instructions below in exact order. Do not skip
any step. Write your reasoning and the actual narration CONTENT in
ENGLISH - but the STRUCTURE LABELS below must stay EXACTLY as shown, in
Portuguese, never translated: "NARRAÇÃO:", "VISUAL:", "[VERIFICAR]",
"[ARQUIVO REAL]". Do not write "NARRATION:" or "VISUAL DESCRIPTION:" or
any English version of these labels - use the literal Portuguese tokens
shown, with English text following them.

TOPIC: {tema}

DELIVERY RULES (very important - read carefully):
- Your final answer must contain ONLY the script in the "NARRAÇÃO:"/
  "VISUAL:" format, start to finish. Do NOT write a greeting, a comment
  about the task, or phrases like "Understood" or "Here is". Do NOT
  repeat the step names (STEP 1, BLOCK A, etc.) in the final answer -
  they are only a reasoning guide for you, not part of the delivered text.
- Do NOT write the script twice. Write it once, start to finish, and stop.
- If the TOPIC above does not name a specific company (e.g. it is a
  market/sector trend topic), YOU must pick ONE specific real company to
  be the throughline of the story right in Step 1, and use its REAL NAME
  throughout the script - never leave a blank or placeholder where the
  company name should be. If you are not absolutely certain of a fact
  about it, mark only that fact with [VERIFICAR], but the company NAME
  itself never gets a marker.

FIXED RULES (apply to the whole script):
- Every suggested visual must EXIST in a free stock library (Pexels/
  Envato/Storyblocks): meeting, office, factory, store shelf, city
  traffic, money, on-screen chart, hands typing, paper being signed,
  shipping container. NEVER describe a unique, specific scene that does
  not exist ready-made (forbidden: "the CEO looking out the window that
  day").
- "[ARQUIVO REAL]" may ONLY appear alone on a "VISUAL:" line, never
  inside the "NARRAÇÃO:" text, neither before nor after the word
  "VISUAL:". Use "[ARQUIVO REAL]" on a VISUAL line when the video needs
  something company-specific (logo, product, founder, building) that
  only exists in press/archive photos, not in stock footage. This is an
  editing instruction, not a substitute for the company name and never
  something that appears in the narrated text. WRONG example (never do
  this): "...paid off the debt on time. [ARQUIVO REAL] photo of the
  contract VISUAL: generic b-roll of signing" - here [ARQUIVO REAL] is
  inside the narration, which is FORBIDDEN. RIGHT example: the
  "NARRAÇÃO:" line never mentions [ARQUIVO REAL] under any
  circumstance; if that beat needs a real image, the matching VISUAL
  line is just "VISUAL: [ARQUIVO REAL] photo of the restructuring
  contract", nothing else.
- Each "NARRAÇÃO:" line gets exactly ONE "VISUAL:" line after it, never
  two visual markers for the same narration line.
- FORBIDDEN to write, inside "NARRAÇÃO:" content, any instruction word
  used in this prompt: "mini-hook", "block", "step", "backstory",
  "core"/"miolo" must never appear in the narrated text - these are
  concepts for you to apply, not labels to write out loud. WRONG example
  (never do this): "The first mini-hook: the investigation revealed
  that..." - same mistake as writing "STEP 1" in the middle of the
  script. The mini-hook is just the fact/reveal itself, never announced
  as one.
- VERIFICATION RULE (the most important rule in this list - read
  carefully): by default, mark [VERIFICAR] next to ANY specific number
  about a real company - percentage, R$/US$ amount, headcount, item
  count, exact date - UNLESS it is a widely known, easily checkable fact
  (e.g. a famous company's founding year, who the founder is). You have
  no way to research facts - so the safe default is to mark, not trust
  your own memory. This applies even if the number seems plausible or
  specific enough to feel real - "feeling real" is not the same as
  "being verified". Real example of the mistake this rule exists to
  prevent: a script about a company cited "200 thousand invoices
  altered", "12% of transactions", "R$1.2 billion in lost revenue",
  "15% workforce cut" and a dozen similar numbers - ALL without
  [VERIFICAR], all possibly fabricated. That is a false factual claim
  about a real company if not checked - the single worst error this
  script can have, worse than any pacing or hook problem.
- FORBIDDEN to invent an ordinary person: never create the name of an
  employee, manager, customer, or meeting participant who is not a real,
  well-known public figure (a famous founder/CEO, for example). Putting
  words ("said that...") in the mouth of a made-up person is the same
  severity of error as a number without [VERIFICAR] - it is a false
  claim about a person nobody can verify. If you need to illustrate a
  human reaction, describe it generically ("a restaurant manager
  noticed that..."), never invent a proper name for that person.
- Explain technical jargon (e.g. "M&A", "bank spread") only when it is
  genuinely obscure to a layperson. Do NOT explain a word the audience
  already understands from context (do not do this: "crisis committee,
  which is an emergency management group", or "conference call, which
  is an online meeting" - nobody needs that explained). And when you do
  explain something, vary the phrasing - do not repeat the "X, which is
  Y" formula every time, it sounds robotic when it happens several times
  in the same script.
- Short sentences, spoken language (this will be narrated aloud, not
  read).
- FORBIDDEN to use these stock phrases: "but nobody expected", "and
  that's when everything changed", "but the story doesn't end there",
  "but there was a problem".

STEP 1 - DEFINE THE ANGLE (write this before the script itself, in up to
2 sentences): Answer: what is the least obvious point of view on this
topic? What question will keep someone watching until the end? Is there
a twist or irony? If the topic does not name a company, say here which
real company you chose for the story.

STEP 2 - WRITE THE SCRIPT IN THIS ORDER AND THIS LENGTH:
IMPORTANT: the ranges below are the MINIMUM acceptable, not the target.
Always write near the TOP of each range, never the bottom - a script
that is too short is the most common and most avoidable mistake.

BLOCK A - INTRO (2 to 4 sentences, 60 to 90 words):
Open with a number, claim, or strange situation. Do NOT say the company
name or the ending yet. End the intro with an implied question (the
viewer should be left wondering "so, what happened?").

BLOCK B - BACKSTORY (280 to 350 words):
Explain the setting as if the person knows nothing about the topic.
Develop the context with detail - era, market, the people involved.
Somewhere in the middle of this block, insert ONE fact, number, or odd
detail that works as a mini-hook (example of a mini-hook: "and mind you,
this was happening at a company that had nearly shut its doors three
years earlier").

BLOCK C - CORE / MIDDLE (750 to 950 words):
Tell the central decision or conflict. Explain the management reasoning
behind the decision (not just the fact, the WHY) - develop each step of
the decision in detail, do not summarize. Insert at least THREE
mini-hooks throughout this block (a new fact, small reveal, or question),
roughly one every 200-250 words - do not save everything for the end.

BLOCK D - CONNECTION TO THE FUTURE OR CONCLUSION (180 to 230 words):
If the matter is still unfolding today: say what it signals for the
future of the sector. If it is a closed case: write the central
management lesson, without sounding like a bumper-sticker moral. End
with an impactful line.

STEP 3 - OUTPUT FORMAT (mandatory, follow this example exactly):
Each sentence or paragraph of the script becomes a "NARRAÇÃO:" line
followed, on a SEPARATE LINE (press Enter - never on the same line), by
a "VISUAL:" line. Formatting example (do not copy the content, only the
format - note NARRAÇÃO and VISUAL are ALWAYS two different lines, and
the label itself stays in Portuguese exactly as written, English content
follows it):

NARRAÇÃO: In 2015, a company nearly went bankrupt with billions in debt.
VISUAL: generic b-roll of a falling line chart on screen

NARRAÇÃO: Five years later, it had become one of the biggest in the
world in its sector.
VISUAL: generic b-roll of a factory in operation, production line

Repeat this pattern ("NARRAÇÃO:" on one line, "VISUAL:" on the next)
start to finish, without skipping any sentence, and never merging the
two onto one line. Do not use block titles (A, B, C, D) in the final
text - they are only a writing guide for you, the result must read as
one continuous narrated text.

BEFORE ANSWERING, check: (1) does every line have "NARRAÇÃO:" and
"VISUAL:" on SEPARATE lines, never merged? (2) does the company name
stay out of the intro, but appear (real name, never a placeholder) in
the rest of the script? (3) when used, is "[ARQUIVO REAL]" ONLY on the
VISUAL line, never inside the narrated text? (4) are there at least 4
mini-hooks total (1 in backstory + 3 in the core) - AND is the word
"mini-hook" itself absent from every NARRAÇÃO line? (5) does the whole
script add up to at least 1300 words of narration - if it's shorter, GO
BACK and develop each block further, especially the CORE block? (6) did
you write the script only ONCE, with no commentary and no repeated step
names? (7) COUNT how many specific numbers (%, R$/US$, quantity, exact
date) appear in the script - does each one have [VERIFICAR] next to it,
except the ones that are widely known public facts? If any specific
number lacks [VERIFICAR] and you are not absolutely certain of it, add
it now. If any answer is no, fix it before delivering.
"""

AVALIACAO_PROMPT_EN = """You are a YouTube audience-retention critic, business/management niche,
long-form video (not Shorts). Evaluate the script below following the
response TEMPLATE at the end EXACTLY. Fill every field, skip none. Be
direct - if something is weak, say it is weak. Write your reasoning in
ENGLISH, but the response template's FIELD NAMES must stay EXACTLY as
shown below, in Portuguese, never translated - only the content you
write after each field name should be in English.

SCRIPT TO EVALUATE:
{roteiro}

Before filling the template, check these 5 points in the script:
1. Does the opening hook (first 2-4 sentences) reveal the company name
   or the ending? If so, that is a problem.
2. Does every block (backstory, core, conclusion) have at least one new
   fact, reveal, or question (a mini-hook)? Or does the text just list
   facts in sequence with nothing new holding attention?
3. Is there any jargon from business/management left unexplained in
   plain language right after it appears?
4. Is the ending specific to this story, or could it be pasted into any
   video on the channel (a generic line like "and that's the lesson
   here")?
5. Is there any spot where the visual description ("VISUAL:") looks like
   a unique moment that does NOT exist ready-made in a stock library?
   WARNING: the goal here is the OPPOSITE of what it seems -
   "VISUAL: generic b-roll of..." is the CORRECT format and should never
   be flagged as a problem, because stock libraries are full of generic
   footage. The real problem is when the script asks for something
   hyper-specific to the company (e.g. "VISUAL: photo of the CEO signing
   THIS specific contract in 2016") without marking [ARQUIVO REAL] - that
   is when you should flag it, and the fix is to ADD [ARQUIVO REAL] or
   swap it for something MORE generic, never to ask for something even
   more specific.
6. Does the word "mini-hook" (or "block", "step", "backstory", "core")
   appear literally WRITTEN inside a NARRAÇÃO line? This is always an
   error - these are instruction concepts, never narrated text. Example
   of the mistake: "The first mini-hook: the investigation revealed
   that...".
7. COUNT the specific numbers in the script. Do this for real, line by
   line, start to finish - do NOT stop after finding 2 or 3, the script
   may have 15, 20, or more. For EVERY NARRAÇÃO line, ask: is there a
   percentage, R$/US$, headcount, or exact date here? If so, does it
   have [VERIFICAR] next to it, OR is it a very well-known public fact
   (e.g. a famous company's founding year)? IMPORTANT: a [VERIFICAR]
   anywhere nearby on the SAME NARRAÇÃO line already marks the number -
   do not demand one marker glued to every digit, and never list as a
   problem a number that already has [VERIFICAR] on its line. List ALL
   that genuinely lack it, not just the first 2-3 you find. If there are 3 or more specific numbers
   without [VERIFICAR] and not a well-known fact, that is a SERIOUS
   problem - the script may be fabricating statistics about a real
   company, which is worse than any pacing or hook problem.
8. Is there any ORDINARY PERSON NAMED by their real name (employee,
   manager, customer, meeting participant) who is not a known public
   figure (a CEO/founder)? Naming an ordinary person and putting speech
   ("said that...") in their mouth is always fabrication, even without a
   number attached - flag it as a serious problem, same severity as a
   number without [VERIFICAR].
9. Now check the EVENTS, not the numbers. Go line by line and ask of each
   narrative beat: did this specific thing actually happen, and can a
   viewer verify it? Reports, lawsuits, investigations, viral videos,
   press conferences, internal meetings, strategy decisions - each is a
   factual claim about a real company and needs [VERIFICAR] unless it is
   widely known. A script can have every number marked and still be
   entirely fabricated at the plot level; that exact failure already
   happened here and was wrongly approved. Treat an unverified PLOT as
   more serious than an unverified number, never less.
10. Does the script avoid naming the company while still making it
   obvious which one it is? Check whether founding year, sector, funding
   rounds, IPO date and valuation together point at one identifiable
   company. If so, flag it - the rule is to NAME the real company in the
   body of the script, and half-anonymity gives no protection while
   breaking that rule.

RESPONSE TEMPLATE (fill exactly like this):

NOTA DO GANCHO (0 a 10): [number]
MOTIVO: [1-2 sentences]

PONTOS DE QUEDA: [list each one found, format "Bloco X: [reason]". If
none found, write "Nenhum encontrado".]

MINI-GANCHOS FALTANDO: [list which block is missing a mini-hook, or
write "Todos os blocos têm mini-gancho"]

JARGÃO NÃO EXPLICADO: [quote the passage, or write "Nenhum encontrado"]

FECHO: [specific or generic - justify in 1 sentence]

VISUAIS PROBLEMÁTICOS: [quote the problematic VISUAL: line, or write
"Nenhum encontrado"]

RÓTULO DE INSTRUÇÃO VAZADO: [quote the line if "mini-gancho"/"bloco"/
"passo" appears written in the narration, or write "Nenhum encontrado"]

NÚMEROS SEM VERIFICAR: [list ALL specific numbers without [VERIFICAR]
that are not a well-known fact - count the whole script, not just the
start. Or write "Nenhum encontrado"]

PESSOA INVENTADA: [quote name and passage if there is an ordinary person
(not a public figure) named by a proper name, or write "Nenhuma
encontrada"]

EVENTO SEM VERIFICAR: [list EVERY narrative EVENT presented as fact that
carries no [VERIFICAR] and is not common public knowledge - a lawsuit, an
investigation, a consumer-group report, a viral video, a press release, a
boardroom debate, an internal decision, a policy change. This is NOT about
numbers (that is the field above) - it is about the STORY ITSELF being
possibly invented. A real failure that happened: a script described a
consumer watchdog report, a viral TikTok video, and an internal executive
debate, all with confident dates, none marked - the numbers were all
marked, so it was approved, and the entire PLOT was unverified fiction
about a real company. Especially flag any passage imputing DELIBERATE BAD
FAITH (quietly targeting users, hiding fees on purpose, refining
algorithms to exploit) - that is an accusation, not a description, and
always needs [VERIFICAR]. Or write "Nenhum encontrado"]

EMPRESA IDENTIFICÁVEL MAS NÃO NOMEADA: [WARNING - the INTRO does not
count here: it hides the company name ON PURPOSE, that is the video's
hook and a fixed rule of this channel. NEVER ask to name the company in
the intro, the opening or the first lines - that request contradicts the
rule the writer must follow, so he can never satisfy it, and the script
stays stuck failing forever. What you judge in this field is the BODY
(backstory, core, conclusion): there the script must name the real
company. If it avoids the name yet piles up details that
identify one specific company anyway (founding year + sector + funding
round + IPO date + valuation), that is the worst of both worlds: no
generic-discussion protection, and the naming rule broken. Quote the
identifying details if this happens, or write "Nenhum encontrado"]

CHANCE DE RETENÇÃO: [baixa / média / alta]

MUDANÇAS OBRIGATÓRIAS: [objective list of what to change, essentials
only - if there is anything in the "RÓTULO DE INSTRUÇÃO VAZADO",
"NÚMEROS SEM VERIFICAR", "PESSOA INVENTADA", "EVENTO SEM VERIFICAR" or
"EMPRESA IDENTIFICÁVEL MAS NÃO NOMEADA" fields, it ALWAYS goes
here as mandatory, no exception. If nothing is mandatory, write
"Nenhuma".

HOW TO WRITE EACH ITEM (hard rule - the reader is the scriptwriter, who
can only edit text and cannot research anything):
- One item per line, starting with an IMPERATIVE VERB (Add, Remove,
  Replace, Rewrite, Name) and saying WHERE to act.
- FORBIDDEN to paste a bare list of data here. Writing only
  "R$ 2.5 billion, 24%, 2015, 2019" is NOT a change - the writer gets it
  with no instruction and returns the same script. The correct form is:
  "Add [VERIFICAR] next to R$ 2.5 billion, 24% and 2019 on the NARRAÇÃO
  lines where they appear".
- FORBIDDEN to ask to "verify the truth", "confirm the source" or
  "research": the writer has no source access at all. The only equivalent
  action he can perform is to ADD [VERIFICAR] to the passage - ask for
  that instead.
- FORBIDDEN to write a suggestion here ("consider", "it would be good",
  "could"). This field is only what FAILS the script. Suggestions belong
  in the fields above, not here.
- Before asking for [VERIFICAR] on a number, CHECK whether it is already
  marked on that line. The pipeline marks numbers automatically before
  you see the script, so asking again is asking for something already
  done - the writer has nothing to do and the whole round is wasted.
- FORBIDDEN to ask to name the company in the intro/opening/first lines.
  The intro hides the name on purpose (it is the hook). If the problem is
  that the BODY never names it, say that: "Name the company in the
  backstory/core".
- If an item was already requested in an earlier round and the writer
  complied, do NOT repeat it. Repeating the same request freezes the
  script in place.]

VEREDITO: [write exactly the word APROVADO if there is no mandatory
change, or exactly the word REPROVADO if there is at least one
mandatory change. Write only that word on this line, in uppercase,
nothing else.]
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

TRADUCAO_PROMPT = """Você traduz um roteiro de vídeo de YouTube do inglês pro português brasileiro
FALADO, não pro português escrito/literal. O objetivo final é uma
narração de voz em áudio - a tradução tem que soar como alguém contando
uma história em português, nunca como um texto traduzido palavra por
palavra.

ROTEIRO EM INGLÊS:
{roteiro_ingles}

REGRAS OBRIGATÓRIAS:
- Traduza SÓ o conteúdo (o texto depois de cada "NARRAÇÃO:" e depois de
  cada "VISUAL:"). NUNCA traduza os próprios rótulos "NARRAÇÃO:" e
  "VISUAL:" - eles já estão em português e têm que continuar exatamente
  assim, palavra por palavra, em cada linha.
- Os marcadores "[VERIFICAR]" e "[ARQUIVO REAL]" são fixos - copie-os
  exatamente onde aparecem, sem traduzir e sem mover de lugar dentro da
  frase.
- PROIBIDO mudar qualquer fato: nome de empresa, número, data, valor,
  nome de pessoa pública têm que ser EXATAMENTE os mesmos do original,
  só a língua muda. Isso inclui manter [VERIFICAR] exatamente nos mesmos
  pontos - não remova a marcação achando que "já dá pra confiar", e não
  adicione marcação nova em número que não tinha.
- Mantenha o número de linhas EXATAMENTE igual: uma linha "NARRAÇÃO:" do
  original vira UMA linha "NARRAÇÃO:" traduzida, nunca junte ou divida
  frases - isso quebraria o casamento com a linha "VISUAL:" correspondente.
- Escreva como se fosse falado em voz alta: frases curtas, conectivos
  naturais em português ("só que", "e olha que", "no fim das contas"),
  não a estrutura de frase do inglês traduzida ao pé da letra. Ajuste a
  ordem das palavras, troque expressões idiomáticas por equivalentes em
  português - o objetivo é soar como um brasileiro contando a história,
  não como uma tradução.
- Termos técnicos que o roteiro já tinha traduzido/explicado em inglês,
  mantenha a mesma explicação, só em português.
- PRESERVE a voz de primeira pessoa do PLURAL onde ela existir no
  original ("vamos aos números", "repare nisso", "olha o tamanho disso").
  Essa voz de guia é proposital, é o que dá a sensação de alguém
  conduzindo o espectador - traduzir isso pra terceira pessoa impessoal
  ("é possível observar que...") mata justamente o efeito. Se o inglês
  tinha "now look at what happens", o português é "agora repare no que
  acontece", não "observa-se que ocorre".
- NUNCA transforme nada em primeira pessoa do SINGULAR na tradução: não
  invente "eu descobri", "eu analisei", "na minha opinião" onde o
  original não tinha - a narração é sintética e o autor não apurou nada,
  então isso viraria uma alegação pessoal falsa.

Responda com o ROTEIRO COMPLETO traduzido, do início ao fim, no mesmo
formato "NARRAÇÃO:"/"VISUAL:" linha por linha, sem comentário sobre a
tarefa, sem repetir nomes de passo, sem escrever o roteiro duas vezes.
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


def _contexto_do_modelo(m):
    """
    Lê o context_window que a Groq devolve como campo EXTRA (o tipo Model
    do SDK da OpenAI não tem esse campo, então ele fica em model_extra).
    Devolve None quando não vem - nesse caso o modelo NÃO é descartado,
    só entra sem garantia.
    """
    valor = getattr(m, "context_window", None)
    if valor is None:
        extras = getattr(m, "model_extra", None) or {}
        valor = extras.get("context_window")
    try:
        return int(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


# Contexto mínimo pra este pipeline. O prompt do crítico embute o roteiro
# inteiro e passa de 8 mil tokens com folga - um modelo de 4.096 (como o
# allam-2-7b, que aparece na lista ao vivo) recusa o pedido na hora com
# "Please reduce the length of the messages". Descartar antes de tentar
# evita gastar uma chamada e um erro confuso.
CONTEXTO_MINIMO_NECESSARIO = 16000


def _obter_modelos_groq_ao_vivo():
    """
    Consulta a API do Groq pra saber quais modelos a SUA chave específica
    pode usar agora - em vez de depender de uma lista fixa que erra sempre
    que a conta não tem acesso a um modelo específico, ou o catálogo muda.

    Também descarta modelo com janela de contexto pequena demais pro
    tamanho de prompt deste pipeline (ver CONTEXTO_MINIMO_NECESSARIO).
    """
    global _modelos_groq_ao_vivo
    if _modelos_groq_ao_vivo is not None:
        return _modelos_groq_ao_vivo
    try:
        resposta = client_groq.models.list()
        ids = []
        descartados_por_contexto = []
        for m in resposta.data:
            if any(p in m.id.lower() for p in _PALAVRAS_MODELO_IGNORAR):
                continue
            contexto = _contexto_do_modelo(m)
            if contexto is not None and contexto < CONTEXTO_MINIMO_NECESSARIO:
                descartados_por_contexto.append(f"{m.id} ({contexto})")
                continue
            ids.append(m.id)
        print(f"    (modelos disponíveis nessa chave Groq: {', '.join(ids)})")
        if descartados_por_contexto:
            print(
                "    (descartados por contexto pequeno demais: "
                f"{', '.join(descartados_por_contexto)})"
            )
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


# Assinaturas do erro "o PROMPT (entrada) é grande demais". É diferente de
# cota estourada e de resposta cortada por max_tokens (saída) - e a
# confusão entre os três já produziu uma mensagem de erro que culpava a
# cota quando o problema real era o prompt inflando entre as tentativas.
_MARCAS_ERRO_CONTEXTO = (
    "context_length_exceeded",
    "reduce the length of the messages",
    "maximum context length",
)


def _erro_e_de_contexto(erro):
    texto = str(erro).lower()
    return any(marca.lower() in texto for marca in _MARCAS_ERRO_CONTEXTO)


_MENSAGEM_ERRO_CONTEXTO = (
    "Nenhum modelo disponível nesta chave Groq aceitou o tamanho deste "
    "prompt (erro de contexto, não de cota - esperar não resolve).\n"
    "Isso quase sempre significa que os modelos grandes (gpt-oss-120b/20b, "
    "131 mil tokens de contexto) estão indisponíveis ou com cota estourada "
    "agora, e sobraram só modelos de contexto pequeno (ex: allam-2-7b, com "
    "4 mil) - que não cabem o roteiro inteiro que o crítico precisa ler.\n"
    "O que fazer: espere a cota dos modelos grandes voltar (é o caso mais "
    "comum), confira console.groq.com/dashboard/limits, ou rode com "
    "USAR_NUVEM = False pra usar o Ollama local.\n"
    "Erro original da API:\n{erro}"
)


def _chamar_groq_com_fallback(messages, temperature, max_tokens):
    global _modelo_groq_confirmado

    if _modelo_groq_confirmado:
        ordem = [_modelo_groq_confirmado] + [
            m for m in MODELOS_GROQ_FALLBACK if m != _modelo_groq_confirmado
        ]
    else:
        ordem = list(MODELOS_GROQ_FALLBACK)

    ultimo_erro = None
    houve_erro_de_contexto = False
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
            if _erro_e_de_contexto(e):
                # CORREÇÃO: janela de contexto é POR MODELO (gpt-oss tem
                # 131 mil tokens, allam-2-7b tem 4 mil), então este erro
                # NÃO significa que o prompt é grande pra todos - só pra
                # este. Abortar aqui (como eu fazia antes) impedia de
                # tentar um modelo maior que daria conta. Então: pula.
                houve_erro_de_contexto = True
                print(
                    f"    Aviso: modelo Groq '{modelo}' recusou por janela de "
                    "contexto pequena pro tamanho deste prompt - tentando um "
                    "modelo com contexto maior..."
                )
                if _modelo_groq_confirmado == modelo:
                    # não fixa um modelo pequeno como "o confirmado"
                    _modelo_groq_confirmado = None
                ultimo_erro = e
                continue
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
            if _erro_e_de_contexto(e):
                houve_erro_de_contexto = True
                print(
                    f"    Aviso: modelo Groq '{modelo}' (da lista ao vivo) "
                    "recusou por janela de contexto pequena - tentando o "
                    "próximo..."
                )
                ultimo_erro = e
                continue
            print(
                f"    Aviso: modelo Groq '{modelo}' (da lista ao vivo) falhou "
                f"({type(e).__name__}) - tentando o próximo..."
            )
            ultimo_erro = e
            continue

    # Só agora, com TODOS os modelos esgotados, dá pra dizer o que
    # aconteceu de verdade: se algum recusou por contexto e nenhum
    # funcionou, o prompt é grande pros modelos que esta chave tem.
    if houve_erro_de_contexto:
        raise RuntimeError(
            _MENSAGEM_ERRO_CONTEXTO.format(erro=ultimo_erro)
        ) from ultimo_erro

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


class _RespostaOllamaNativa:
    """
    Adaptador: deixa a resposta do endpoint NATIVO do Ollama com a mesma
    forma que o resto do código espera (resposta.choices[0].message.content
    e .finish_reason), pra não precisar mudar chamar_llm() nem nada abaixo.
    """

    class _Escolha:
        class _Mensagem:
            def __init__(self, content):
                self.content = content

        def __init__(self, content, finish_reason):
            self.message = self._Mensagem(content)
            self.finish_reason = finish_reason

    def __init__(self, content, finish_reason):
        self.choices = [self._Escolha(content, finish_reason)]


def _chamar_ollama_nativo(mensagens, temperature, max_tokens):
    """
    Usa o endpoint NATIVO do Ollama (/api/chat) em vez do compatível com
    OpenAI (/v1/chat/completions).

    MOTIVO (confirmado em várias fontes e em testes diretos de terceiros):
    o endpoint /v1 do Ollama IGNORA o num_ctx e roda tudo no padrão do
    daemon (2048-4096 tokens), TRUNCANDO o prompt em silêncio - sem erro,
    sem aviso, sem nada no retorno. Só aparece um "truncating input
    prompt" no log do servidor Ollama, que ninguém está olhando. Os
    prompts deste pipeline passam de 2.600 tokens (o do crítico, com o
    roteiro inteiro dentro, passa de 8.000), então no /v1 o crítico
    avaliaria um roteiro cortado no meio achando que leu tudo. O /api/chat
    respeita options.num_ctx de verdade.
    """
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": MODEL,
            "messages": mensagens,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": OLLAMA_NUM_CTX,
            },
        },
        timeout=OLLAMA_TIMEOUT_S,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Ollama retornou erro {resp.status_code} - {resp.text[:300]}\n"
            "Confira se o Ollama está rodando (abra http://localhost:11434 "
            "no navegador; tem que aparecer 'Ollama is running') e se o "
            f"modelo '{MODEL}' já foi baixado (ollama pull {MODEL})."
        )
    dados = resp.json()
    conteudo = (dados.get("message") or {}).get("content", "") or ""
    # No nativo o campo é done_reason ("stop" | "length" | ...) - traduz
    # pro nome que o resto do código já usa
    done_reason = dados.get("done_reason")
    finish_reason = "length" if done_reason == "length" else "stop"
    return _RespostaOllamaNativa(conteudo, finish_reason)


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
        resposta = _chamar_ollama_nativo(mensagens, temperature, max_tokens)

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
# AGENTE 0 - PESQUISADOR DE FATOS (roda ANTES do roteirista)
# =========================================================================
# Por que existe: o roteirista não tem como consultar nada, então tudo que
# ele escreve sai da memória do modelo - e memória de modelo inventa com
# confiança. Foi assim que um roteiro aprovado descreveu relatório, vídeo
# viral e reunião de diretoria que nunca existiram. O crítico não resolve
# isso: ele também não pesquisa, só consegue MARCAR a dúvida.
#
# Este agente levanta o material ANTES de escrever, de fontes abertas e
# sem chave de API, e entrega um dossiê que vai junto no prompt. O efeito
# é o roteiro passar a contar uma história que existe, em vez de uma
# história plausível.
#
# NÃO substitui sua revisão: Wikipédia e manchete são fonte secundária. O
# que muda é o tamanho do trabalho - em vez de checar 20 fatos do zero,
# você confere um checklist que já aponta quais números aparecem no
# material levantado e quais apareceram do nada.

_PESQUISA_HEADERS = {
    # A Wikimedia pede um User-Agent identificável; sem isso a API pode
    # responder 403 em vez do JSON.
    "User-Agent": "PipelineCanalYouTube/1.0 (uso pessoal, roteiro de video)"
}

# Seções de artigo que interessam pra esse canal (história, crise,
# polêmica) - o resto (lista de produtos, ligações externas, elenco de
# diretoria atual) só gastaria contexto.
_SECOES_INTERESSANTES = (
    "história", "historia", "fundação", "fundacao", "origem", "origens",
    "crise", "controvérsia", "controversia", "polêmica", "polemica",
    "processo", "processos", "escândalo", "escandalo", "expansão",
    "expansao", "aquisição", "aquisicao", "aquisições", "aquisicoes",
    "modelo de negócio", "modelo de negocios", "negócios", "negocios",
    "crítica", "critica", "críticas", "criticas", "financeiro",
    "resultados", "reestruturação", "reestruturacao", "falência",
    "falencia", "history", "founding", "origins", "controversy",
    "criticism", "lawsuit", "lawsuits", "expansion", "acquisitions",
    "business model", "finances", "financial", "bankruptcy",
)

# Propriedades do Wikidata que viram fato estruturado no dossiê. São
# dados com fonte, data e unidade - o oposto do número que o modelo
# "lembra".
_PROPRIEDADES_WIKIDATA = {
    "P571": "Fundação",
    "P112": "Fundador(es)",
    "P169": "CEO",
    "P159": "Sede",
    "P452": "Setor",
    "P1128": "Funcionários",
    "P2139": "Receita",
    "P2295": "Lucro/prejuízo líquido",
    "P1454": "Forma jurídica",
}

_UNIDADES_WIKIDATA = {
    "Q4917": "US$", "Q4916": "€", "Q41726": "R$", "Q25224": "£",
}


def _pesquisa_get(url, params, timeout=None):
    """GET curto e tolerante: qualquer falha (sem internet, 403, timeout,
    JSON quebrado) devolve None, e quem chamou segue sem aquela fonte. O
    pipeline nunca pode morrer porque a Wikipédia demorou pra responder."""
    try:
        resposta = requests.get(
            url,
            params=params,
            headers=_PESQUISA_HEADERS,
            timeout=timeout or PESQUISA_TIMEOUT_S,
        )
        resposta.raise_for_status()
        return resposta.json()
    except Exception as erro:
        print(f"    (pesquisa: {url.split('/')[2]} não respondeu - {type(erro).__name__})")
        return None


def _quebrar_em_secoes(texto):
    """Separa o texto puro de um artigo da Wikipédia em (título, conteúdo).
    Com explaintext=1 os títulos vêm como '== História ==' em linha
    própria."""
    pedacos = re.split(r"\n(={2,}[^=\n]+={2,})\n", texto)
    secoes = [("(introdução)", pedacos[0])]
    for i in range(1, len(pedacos) - 1, 2):
        secoes.append((pedacos[i].strip("= ").strip(), pedacos[i + 1]))
    return secoes


def _resumir_artigo(texto, limite):
    """Fica com a introdução + as seções que interessam, dentro do limite
    de caracteres. Contexto é recurso escasso aqui (o modelo local tem
    16k no total, e o prompt do roteirista já é grande), então o dossiê
    precisa caber, não ser completo."""
    partes = []
    total = 0
    for titulo, conteudo in _quebrar_em_secoes(texto):
        conteudo = conteudo.strip()
        if not conteudo:
            continue
        chave = titulo.lower()
        interessa = titulo == "(introdução)" or any(
            s in chave for s in _SECOES_INTERESSANTES
        )
        if not interessa:
            continue
        disponivel = limite - total
        if disponivel <= 200:
            break
        trecho = conteudo[:disponivel]
        partes.append(f"[{titulo}]\n{trecho}")
        total += len(trecho)
    return "\n\n".join(partes)


# Sinais de que o artigo encontrado é mesmo de uma organização, e não de
# uma cidade, um filme ou uma pessoa com nome parecido.
_SINAIS_DE_EMPRESA = (
    "empresa", "companhia", "corporação", "corporacao", "multinacional",
    "conglomerado", "holding", "startup", "s.a.", "s/a", "ltda", "banco",
    "varejista", "fabricante", "operadora", "transportadora", "fundada",
    "fundado", "sediada", "company", "corporation", "founded",
    "headquartered", "inc.", "manufacturer", "retailer",
)


def _pontuar_candidato(titulo, termo, intro, e_desambiguacao):
    """
    Nota de um artigo candidato (maior = melhor). Devolve None pro que
    deve ser descartado de saída.

    Existe porque pegar o primeiro resultado da busca é um chute: "Ambev"
    acha a empresa, mas um termo mais genérico cai fácil numa página de
    desambiguação, numa lista ou no artigo da cidade de mesmo nome - e aí
    o dossiê inteiro fica sobre o assunto errado, que é pior do que não
    ter dossiê nenhum (o roteirista confia no material).
    """
    if e_desambiguacao:
        return None
    titulo_n = _normalizar_para_comparar(titulo)
    termo_n = _normalizar_para_comparar(termo)
    intro_n = _normalizar_para_comparar(intro)
    if titulo_n.startswith("lista de") or titulo_n.startswith("anexo"):
        return None
    # "X pode referir-se a" é desambiguação sem a marca formal.
    if "pode referir se a" in intro_n[:200] or "may refer to" in intro_n[:200]:
        return None

    nota = 0
    if titulo_n == termo_n:
        nota += 10
    elif termo_n in titulo_n or titulo_n in termo_n:
        nota += 5
    nota += 3 * sum(1 for sinal in _SINAIS_DE_EMPRESA
                    if sinal in intro_n[:600])
    if len(intro) > 300:
        nota += 1
    return nota


def buscar_wikipedia(termo, idioma="pt", limite_caracteres=3500):
    """
    Acha o artigo certo e devolve {titulo, url, texto, qid} ou None.

    Três chamadas à API aberta da MediaWiki (sem chave, sem registro):
      1. list=search - até 5 candidatos, em vez de aceitar o primeiro;
      2. prop=extracts|pageprops (só a introdução, exlimit=5) - texto pra
         escolher entre eles, a marca de página de desambiguação e o
         wikibase_item, que é o ID EXATO desse artigo no Wikidata;
      3. prop=extracts do vencedor - o artigo inteiro.

    O qid da chamada 2 é o que evita o segundo chute: sem ele, a busca no
    Wikidata é por nome e pode cair noutra entidade com nome parecido.
    """
    base = f"https://{idioma}.wikipedia.org/w/api.php"
    busca = _pesquisa_get(base, {
        "action": "query", "list": "search", "srsearch": termo,
        "srlimit": 5, "format": "json",
    })
    if not busca:
        return None
    candidatos = [r["title"] for r in busca.get("query", {}).get("search", [])]
    if not candidatos:
        return None

    previa = _pesquisa_get(base, {
        "action": "query", "prop": "extracts|pageprops",
        "ppprop": "disambiguation|wikibase_item",
        "exintro": 1, "explaintext": 1, "exlimit": len(candidatos),
        "redirects": 1, "titles": "|".join(candidatos), "format": "json",
    })
    paginas = (previa or {}).get("query", {}).get("pages", {})

    melhor = None
    for pagina in paginas.values():
        titulo = pagina.get("title", "")
        props = pagina.get("pageprops", {})
        nota = _pontuar_candidato(
            titulo, termo, pagina.get("extract", "") or "",
            "disambiguation" in props,
        )
        if nota is None:
            continue
        if melhor is None or nota > melhor["nota"]:
            melhor = {"nota": nota, "titulo": titulo,
                      "qid": props.get("wikibase_item")}

    # Nenhum candidato prestou (todos desambiguação/lista) ou a prévia não
    # veio: cai no primeiro resultado da busca, que é o comportamento
    # antigo - pior escolha, mas melhor que desistir.
    titulo_escolhido = melhor["titulo"] if melhor else candidatos[0]
    qid = melhor["qid"] if melhor else None

    conteudo = _pesquisa_get(base, {
        "action": "query", "prop": "extracts", "explaintext": 1,
        "exsectionformat": "plain", "redirects": 1,
        "titles": titulo_escolhido, "format": "json",
    })
    if not conteudo:
        return None
    for pagina in conteudo.get("query", {}).get("pages", {}).values():
        texto = pagina.get("extract", "")
        if not texto:
            continue
        titulo_final = pagina.get("title", titulo_escolhido)
        return {
            "titulo": titulo_final,
            "url": f"https://{idioma}.wikipedia.org/wiki/"
                   + titulo_final.replace(" ", "_"),
            "texto": _resumir_artigo(texto, limite_caracteres),
            "qid": qid,
            "candidatos": candidatos,
        }
    return None


def _valor_wikidata(valor_bruto):
    """Traduz o valor de uma claim do Wikidata pra texto. Devolve
    (texto, qid_pra_resolver) - quando o valor é outra entidade, o nome
    dela só vem numa segunda chamada."""
    if not isinstance(valor_bruto, dict):
        return None, None
    tipo = valor_bruto.get("type")
    valor = valor_bruto.get("value")
    if tipo == "time" and isinstance(valor, dict):
        # formato "+1999-08-02T00:00:00Z"
        achado = re.search(r"([+-])(\d{4})-(\d{2})-(\d{2})", valor.get("time", ""))
        if not achado:
            return None, None
        _, ano, mes, dia = achado.groups()
        if mes != "00" and dia != "00":
            return f"{dia}/{mes}/{ano}", None
        return ano, None
    if tipo == "quantity" and isinstance(valor, dict):
        quantidade = valor.get("amount", "").lstrip("+")
        unidade_id = (valor.get("unit") or "").rsplit("/", 1)[-1]
        unidade = _UNIDADES_WIKIDATA.get(unidade_id, "")
        try:
            bruto = float(quantidade)
        except ValueError:
            return (f"{unidade} {quantidade}".strip()), None
        cheio = f"{bruto:,.0f}".replace(",", ".")
        # Mostra os dois formatos de propósito: "14,47 bilhões" é o que o
        # roteirista vai narrar, e o número cheio é o que faz o checklist
        # casar quando o roteiro escrever o valor por extenso.
        if abs(bruto) >= 1_000_000_000:
            legivel = f"{bruto / 1_000_000_000:.2f}".replace(".", ",") + " bilhões"
        elif abs(bruto) >= 1_000_000:
            legivel = f"{bruto / 1_000_000:.2f}".replace(".", ",") + " milhões"
        else:
            return (f"{unidade} {cheio}".strip()), None
        return (f"{unidade} {legivel} ({cheio})".strip()), None
    if tipo == "wikibase-entityid" and isinstance(valor, dict):
        return None, valor.get("id")
    if isinstance(valor, str):
        return valor, None
    return None, None


def _ano_da_claim(claim):
    """Ano do qualificador 'ponto no tempo' (P585), quando existe - é o
    que diferencia 'receita de 2015' de 'receita de 2024'."""
    for qualificador in claim.get("qualifiers", {}).get("P585", []):
        texto, _ = _valor_wikidata(qualificador.get("datavalue", {}))
        if texto:
            return texto[-4:]
    return None


def buscar_wikidata(termo, idioma="pt", qid=None):
    """
    Fatos estruturados (fundação, sede, fundador, funcionários, receita).
    Devolve lista de strings prontas pro dossiê. Vale a pena porque aqui
    o número vem com unidade e ano, não da memória do modelo.

    Quando o artigo da Wikipédia já entregou o wikibase_item (qid), usa
    ele direto: é o MESMO assunto do artigo, sem risco de a busca por
    nome cair noutra entidade parecida. A busca por nome fica só como
    plano B.
    """
    entidade_id = qid
    if not entidade_id:
        busca = _pesquisa_get("https://www.wikidata.org/w/api.php", {
            "action": "wbsearchentities", "search": termo, "language": idioma,
            "uselang": idioma, "limit": 1, "format": "json",
        })
        if not busca or not busca.get("search"):
            return [], None
        entidade_id = busca["search"][0]["id"]

    dados = _pesquisa_get("https://www.wikidata.org/w/api.php", {
        "action": "wbgetentities", "ids": entidade_id, "props": "claims",
        "format": "json",
    })
    if not dados:
        return [], None
    claims = dados.get("entities", {}).get(entidade_id, {}).get("claims", {})

    fatos = []
    qids_pendentes = {}
    for propriedade, rotulo in _PROPRIEDADES_WIKIDATA.items():
        melhor_texto = None
        melhor_ano = None
        for claim in claims.get(propriedade, []):
            datavalue = claim.get("mainsnak", {}).get("datavalue", {})
            texto, qid = _valor_wikidata(datavalue)
            ano = _ano_da_claim(claim)
            # Entre várias declarações da mesma propriedade (receita de
            # vários anos), fica com a mais recente.
            if melhor_ano and ano and ano <= melhor_ano:
                continue
            if qid:
                qids_pendentes.setdefault(qid, []).append(len(fatos))
                texto = f"@@{qid}@@"
            if texto:
                melhor_texto, melhor_ano = texto, ano or melhor_ano
        if melhor_texto:
            sufixo = f" (em {melhor_ano})" if melhor_ano else ""
            fatos.append(f"- {rotulo}: {melhor_texto}{sufixo}")

    # Resolve os nomes das entidades citadas (fundador, sede, setor) numa
    # chamada só, em vez de uma por item.
    if qids_pendentes:
        rotulos = _pesquisa_get("https://www.wikidata.org/w/api.php", {
            "action": "wbgetentities", "ids": "|".join(list(qids_pendentes)[:20]),
            "props": "labels", "languages": f"{idioma}|en", "format": "json",
        })
        entidades = (rotulos or {}).get("entities", {})
        for qid in qids_pendentes:
            etiquetas = entidades.get(qid, {}).get("labels", {})
            nome = (etiquetas.get(idioma) or etiquetas.get("en") or {}).get("value", qid)
            fatos = [f.replace(f"@@{qid}@@", nome) for f in fatos]

    return fatos, f"https://www.wikidata.org/wiki/{entidade_id}"


def buscar_manchetes(termo, limite=None):
    """
    Manchetes do Google News RSS: cada uma é um evento com DATA e VEÍCULO,
    que é exatamente o que falta pro campo "EVENTO SEM VERIFICAR" - o
    roteiro deixa de inventar o enredo e passa a contar o que saiu na
    imprensa, com data conferível.
    """
    from urllib.parse import quote

    limite = limite or PESQUISA_MAX_MANCHETES
    try:
        import feedparser
    except ImportError:
        print("    (pesquisa: feedparser não instalado - pulando manchetes. "
              "Instale com: pip install feedparser)")
        return []

    url = (
        f"https://news.google.com/rss/search?q={quote(termo)}"
        "&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    )
    try:
        feed = feedparser.parse(url)
    except Exception as erro:
        print(f"    (pesquisa: Google News não respondeu - {type(erro).__name__})")
        return []

    # O feedparser NÃO levanta exceção quando a rede falha: devolve um feed
    # vazio com bozo=1 e segue em silêncio. Sem este aviso, ficar sem
    # manchete nenhuma parece "o tema não tem notícia" quando na verdade foi
    # a internet - confundiu o diagnóstico num teste real.
    entradas = getattr(feed, "entries", [])
    if not entradas:
        motivo = getattr(feed, "bozo_exception", None) or getattr(feed, "status", "")
        print(
            "    (pesquisa: Google News não devolveu manchete"
            + (f" - {type(motivo).__name__ if isinstance(motivo, Exception) else motivo}" if motivo else "")
            + ")"
        )
        return []

    manchetes = []
    for entrada in entradas[:limite]:
        titulo = getattr(entrada, "title", "").strip()
        if not titulo:
            continue
        data = ""
        publicado = getattr(entrada, "published_parsed", None)
        if publicado:
            data = f"{publicado.tm_year}-{publicado.tm_mon:02d}-{publicado.tm_mday:02d}"
        veiculo = ""
        fonte = getattr(entrada, "source", None)
        if fonte is not None:
            veiculo = getattr(fonte, "title", "") or ""
        manchetes.append({"data": data, "veiculo": veiculo, "titulo": titulo})
    return manchetes


def definir_entidade_e_termos(tema):
    """
    Uma chamada curta ao LLM só pra decidir O QUE pesquisar. É preciso
    porque o tema costuma vir como manchete ou pergunta ("o erro de
    gestão que quase derrubou um gigante do delivery"), e buscar isso
    literalmente na Wikipédia não devolve nada.

    Formato de linha fixa em vez de JSON: modelo pequeno erra chave e
    vírgula de JSON com frequência, mas acerta "RÓTULO: valor".
    """
    prompt = (
        "Você é um pesquisador. Leia o tema de vídeo abaixo e responda "
        "EXATAMENTE neste formato, sem nenhum comentário:\n\n"
        "EMPRESA: [nome real e oficial de UMA empresa/organização que é o "
        "fio condutor do tema. Se o tema não citar nenhuma, escolha a mais "
        "emblemática do assunto. Nome puro, sem explicação.]\n"
        "TERMOS: [2 a 3 termos de busca separados por | , começando pelo "
        "nome da empresa. Ex: Americanas | Americanas fraude contábil]\n\n"
        f"TEMA: {tema}"
    )
    # 300 e não 30/200: modelo de raciocínio (gpt-oss) gasta parte do teto
    # "pensando" antes de escrever - foi o que já quebrou a tradução de
    # termo de busca do b-roll.
    try:
        resposta = chamar_llm(prompt, temperature=0.2, max_tokens=300, avisar_corte=False)
    except Exception as erro:
        print(f"    (pesquisa: LLM não respondeu na escolha do termo - {type(erro).__name__})")
        return "", [tema]

    empresa = ""
    achado = re.search(r"EMPRESA:\s*(.+)", resposta)
    if achado:
        empresa = achado.group(1).strip().strip("[]*_ ").split("\n")[0]

    termos = []
    achado = re.search(r"TERMOS:\s*(.+)", resposta)
    if achado:
        termos = [
            t.strip().strip("[]*_ ")
            for t in achado.group(1).split("|")
            if t.strip().strip("[]*_ ")
        ]

    # Sem resposta utilizável, pesquisa o próprio tema - pior busca, mas
    # melhor que não pesquisar nada.
    if not empresa and not termos:
        return "", [tema]
    if not termos:
        termos = [empresa]
    if empresa and empresa not in termos:
        termos.insert(0, empresa)
    return empresa, termos[:3]


def _caminho_cache_dossie(tema):
    return PASTA_CACHE_PESQUISA / f"{_slugificar(tema, 60)}.json"


def pesquisar_dossie(tema, usar_cache=True):
    """
    Junta tudo num dossiê só. Devolve dict com entidade, texto, fontes e
    manchetes - ou None se não conseguiu levantar nada (aí o pipeline
    segue como antes, só sem dossiê).

    Tem cache em disco porque "refazer só o roteiro" e cada tentativa do
    loop usariam o mesmo material: repetir a busca seria lento e sem
    ganho nenhum.
    """
    caminho = _caminho_cache_dossie(tema)
    if usar_cache and caminho.exists():
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dossie = json.load(f)
            idade_dias = (
                datetime.now() - datetime.fromisoformat(dossie["gerado_em"])
            ).days
            if idade_dias <= PESQUISA_VALIDADE_CACHE_DIAS:
                print(f"  Dossiê reaproveitado do cache ({caminho.name}, {idade_dias}d).")
                return dossie
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            pass

    print("Pesquisando fatos sobre o tema antes de escrever...")
    entidade, termos = definir_entidade_e_termos(tema)
    print(f"  Assunto central identificado: {entidade or termos[0]}")

    fontes = []
    blocos = []

    artigo = buscar_wikipedia(termos[0])
    if not artigo and entidade:
        artigo = buscar_wikipedia(entidade)
    if not artigo:
        # Artigo em inglês costuma ser mais completo pra empresa de fora.
        artigo = buscar_wikipedia(termos[0], idioma="en")
    if artigo:
        outros = [c for c in artigo.get("candidatos", []) if c != artigo["titulo"]]
        print(
            f"  Wikipédia: {artigo['titulo']} ({len(artigo['texto'])} caracteres)"
            + (f" - escolhido entre {len(artigo['candidatos'])} candidatos; "
               f"os outros eram: {', '.join(outros[:4])}" if outros else "")
        )
        fontes.append(artigo["url"])
        blocos.append(f"=== WIKIPÉDIA - {artigo['titulo']} ===\n{artigo['texto']}")

    fatos, url_wikidata = buscar_wikidata(
        entidade or termos[0], qid=(artigo or {}).get("qid")
    )
    if fatos:
        print(f"  Wikidata: {len(fatos)} fato(s) estruturado(s)")
        if url_wikidata:
            fontes.append(url_wikidata)
        blocos.append("=== FATOS ESTRUTURADOS (Wikidata) ===\n" + "\n".join(fatos))

    manchetes = []
    for termo in termos:
        for item in buscar_manchetes(termo):
            if item["titulo"] not in [m["titulo"] for m in manchetes]:
                manchetes.append(item)
        if len(manchetes) >= PESQUISA_MAX_MANCHETES:
            break
    manchetes = manchetes[:PESQUISA_MAX_MANCHETES]
    if manchetes:
        print(f"  Google News: {len(manchetes)} manchete(s)")
        linhas = [
            f"- {m['data'] or 'sem data'} | {m['veiculo'] or 'veículo não informado'}: {m['titulo']}"
            for m in manchetes
        ]
        blocos.append(
            "=== MANCHETES (Google News - cada uma é um evento datado e "
            "conferível) ===\n" + "\n".join(linhas)
        )

    if not blocos:
        print("  Nenhuma fonte respondeu - seguindo sem dossiê (roteiro "
              "volta a depender só da memória do modelo).")
        return None

    dossie = {
        "tema": tema,
        "entidade": entidade,
        "termos": termos,
        "texto": "\n\n".join(blocos),
        "fontes": fontes,
        "manchetes": manchetes,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        PASTA_CACHE_PESQUISA.mkdir(exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dossie, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

    return dossie


def texto_do_dossie(dossie, limite=None):
    """O dossiê cortado no tamanho que cabe no prompt de quem vai receber
    (o roteirista na primeira escrita leva o completo; nas revisões e no
    crítico vai a versão curta, porque lá o prompt já carrega o roteiro
    inteiro)."""
    if not dossie:
        return ""
    return _truncar(dossie["texto"], limite or PESQUISA_MAX_CHARS_DOSSIE, "dossiê")


def _instrucoes_do_dossie_pt(dossie_texto):
    return (
        "\n\nDOSSIÊ DE PESQUISA (levantado automaticamente ANTES de você "
        "escrever, de fontes abertas):\n"
        f"{dossie_texto}\n\n"
        "COMO USAR O DOSSIÊ (regras duras):\n"
        "- A história do roteiro tem que ser a que está no dossiê. Fato, "
        "evento, data e número que NÃO estão aqui, você não sabe - ou "
        "deixa de fora, ou escreve de forma genérica sem número. Nunca "
        "complete uma lacuna com algo plausível.\n"
        "- As manchetes provam que o evento aconteceu naquela data, e só "
        "isso. Não invente o conteúdo da reportagem a partir do título: "
        "se a manchete diz 'empresa é processada', não escreva o valor do "
        "processo nem o nome do juiz.\n"
        "- Não copie frase da Wikipédia. Reescreva tudo em linguagem "
        "falada - o texto é pra ser narrado, não lido.\n"
        "- Continue marcando [VERIFICAR] em número específico, mesmo nos "
        "que vieram do dossiê. O dossiê é fonte secundária: serve pra "
        "você não inventar, não pra dispensar a conferência final.\n"
        "- Se o dossiê contradiz o TEMA, siga o dossiê e ajuste o ângulo."
    )


def _instrucoes_do_dossie_en(dossie_texto):
    return (
        "\n\nRESEARCH DOSSIER (gathered automatically from open sources "
        "BEFORE you write - it is in Portuguese, your script stays in "
        "English):\n"
        f"{dossie_texto}\n\n"
        "HOW TO USE THE DOSSIER (hard rules):\n"
        "- The story you tell must be the one in the dossier. Any fact, "
        "event, date or number NOT in here is something you do not know - "
        "leave it out, or write it generically with no number. Never fill "
        "a gap with something merely plausible.\n"
        "- The headlines prove an event happened on that date, nothing "
        "more. Do not invent the article's content from its title: if a "
        "headline says 'company sued', do not write the lawsuit's value or "
        "the judge's name.\n"
        "- Do not copy sentences from Wikipedia. Rewrite everything in "
        "spoken language - this text will be narrated, not read.\n"
        "- Keep marking [VERIFICAR] on specific numbers, including the "
        "ones taken from the dossier. It is a secondary source: it keeps "
        "you from inventing, it does not replace the final check.\n"
        "- If the dossier contradicts the TOPIC, follow the dossier and "
        "adjust the angle."
    )


def bloco_dossie_para_prompt(dossie_texto):
    """Mesmo dossiê, instruções no idioma em que o roteiro está sendo
    escrito."""
    if not dossie_texto:
        return ""
    if GERAR_EM_INGLES:
        return _instrucoes_do_dossie_en(dossie_texto)
    return _instrucoes_do_dossie_pt(dossie_texto)


def _variantes_do_numero(trecho):
    """'R$ 2,5 bilhões' -> procura por '2,5' e '2.5' no dossiê. Vírgula e
    ponto decimal trocam de lugar entre fonte brasileira e internacional,
    e o mesmo número aparece das duas formas."""
    digitos = re.search(r"\d[\d.,]*", trecho)
    if not digitos:
        return []
    bruto = digitos.group(0).rstrip(".,")
    variantes = {bruto, bruto.replace(",", "."), bruto.replace(".", ",")}
    # 1.200 e 1200 são o mesmo número escrito de dois jeitos
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", bruto):
        variantes.add(re.sub(r"[.,]", "", bruto))
    return [v for v in variantes if v]


def conferir_numeros_contra_dossie(roteiro, dossie):
    """
    Cruza cada número do roteiro com o material levantado e devolve uma
    lista de {trecho, confere, linha}.

    É o começo da pendência "agente que verifica os [VERIFICAR]" - e é
    honesto sobre o que faz: diz se o número APARECE no material
    pesquisado, não se a afirmação é verdadeira no contexto. Um número
    que não aparece em lugar nenhum do dossiê é quase sempre invenção do
    modelo, e é nele que sua revisão tem que começar.
    """
    if not dossie or not roteiro:
        return []

    dossie_texto = dossie.get("texto", "")
    conferencias = []
    vistos = set()
    for linha in roteiro.splitlines():
        if not _INICIO_LINHA_NARRACAO.match(linha):
            continue
        corte = linha.upper().find("VISUAL:")
        narrada = linha if corte == -1 else linha[:corte]
        for achado in _PADRAO_NUMERO_ESPECIFICO.finditer(narrada):
            trecho = achado.group(0).strip()
            if trecho in vistos:
                continue
            vistos.add(trecho)
            confere = False
            for variante in _variantes_do_numero(trecho):
                if re.search(rf"(?<!\d){re.escape(variante)}(?!\d)", dossie_texto):
                    confere = True
                    break
            conferencias.append({
                "trecho": trecho,
                "confere": confere,
                "linha": narrada.strip()[:160],
            })
    return conferencias


def montar_checklist_verificar(conferencias, fontes):
    """Texto pronto pro relatório: o que bate com o dossiê e o que
    apareceu do nada, que é onde sua revisão começa."""
    if not conferencias:
        return ""
    batem = [c for c in conferencias if c["confere"]]
    nao_batem = [c for c in conferencias if not c["confere"]]

    linhas = [
        f"{len(conferencias)} número(s) específico(s) no roteiro. "
        f"{len(batem)} aparece(m) no material pesquisado, "
        f"{len(nao_batem)} NÃO aparece(m).",
        "",
        "ATENÇÃO: 'aparece no material' não é o mesmo que 'está certo no "
        "contexto' - o dossiê é fonte secundária. Mas todo número da "
        "segunda lista veio da memória do modelo, sem nenhum respaldo: é "
        "por eles que a revisão tem que começar.",
        "",
    ]
    if nao_batem:
        linhas.append("SEM RESPALDO NO DOSSIÊ (confira um por um):")
        for item in nao_batem:
            linhas.append(f"  [ ] {item['trecho']}  ->  {item['linha']}")
        linhas.append("")
    if batem:
        linhas.append("APARECEM NO MATERIAL PESQUISADO (confirme a leitura):")
        for item in batem:
            linhas.append(f"  [ok] {item['trecho']}  ->  {item['linha']}")
        linhas.append("")
    if fontes:
        linhas.append("FONTES CONSULTADAS:")
        linhas.extend(f"  - {f}" for f in fontes)
    return "\n".join(linhas)


# =========================================================================
# AGENTE 2 - ROTEIRISTA
# =========================================================================

# =========================================================================
# ESCRITA POR BLOCOS - como fazer um 7B entregar 1.400 palavras
# =========================================================================
# O problema medido em dois runs reais: pedindo o roteiro inteiro numa
# chamada só, o modelo local devolveu 532 e depois 361 palavras, contra um
# alvo de 1270-1620. O passe de expansão, que existia justamente pra isso,
# ganhou 9 palavras num caso e 1 palavra no outro - ele não resolve, só
# custa mais uma chamada lenta.
#
# A causa não é o prompt: é que modelo pequeno não sustenta texto longo
# num único turno. Ele "conclui" cedo e para. A saída é trocar UMA tarefa
# grande por VÁRIAS pequenas: 300 palavras por chamada é algo que um 7B
# entrega com folga, e seis blocos de 300 somam o vídeo inteiro.
#
# Efeito colateral bom: o progresso fica visível. Em vez de esperar dez
# minutos pra descobrir que saiu curto, aparece a contagem a cada bloco.

PALAVRAS_POR_MINUTO_NARRACAO = 150  # ritmo de narração documental em PT-BR

BLOCOS_DO_ROTEIRO = (
    {
        "nome": "INTRODUÇÃO",
        "minimo": 60, "maximo": 90,
        "pt": "Escreva a ABERTURA do vídeo. Comece com um número, uma "
              "afirmação ou uma situação estranha. NÃO diga o nome da "
              "empresa e NÃO entregue o final. Termine deixando uma "
              "pergunta implícita no ar.",
        "en": "Write the OPENING of the video. Start with a number, a "
              "claim or a strange situation. Do NOT say the company name "
              "and do NOT give away the ending. Close leaving an implicit "
              "question hanging.",
    },
    {
        "nome": "BACKSTORY",
        "minimo": 280, "maximo": 350,
        "pt": "Escreva o CONTEXTO da história, como se a pessoa não "
              "soubesse nada do assunto: a época, o mercado, quem são os "
              "envolvidos. Aqui o nome real da empresa APARECE. No meio "
              "do bloco, encaixe um dado ou fato curioso que segure a "
              "atenção.",
        "en": "Write the BACKGROUND, as if the viewer knew nothing about "
              "the subject: the period, the market, who is involved. The "
              "real company name DOES appear here. Halfway through, drop "
              "one fact or figure that holds attention.",
    },
    {
        "nome": "MIOLO (1 de 3)",
        "minimo": 250, "maximo": 320,
        "pt": "Comece o DESENVOLVIMENTO: apresente a decisão ou o "
              "conflito central e explique o raciocínio de gestão por "
              "trás dele - o porquê, não só o fato. Encaixe uma revelação "
              "ou dado novo neste bloco.",
        "en": "Start the CORE: present the central decision or conflict "
              "and explain the management reasoning behind it - the why, "
              "not just the what. Land one new reveal or fact in this "
              "block.",
    },
    {
        "nome": "MIOLO (2 de 3)",
        "minimo": 250, "maximo": 320,
        "pt": "Continue o DESENVOLVIMENTO: as consequências da decisão e "
              "como a situação evoluiu. Desenvolva cada etapa com "
              "detalhe, sem resumir. Encaixe outra revelação ou dado novo.",
        "en": "Continue the CORE: the consequences of that decision and "
              "how the situation developed. Develop each step in detail, "
              "do not summarize. Land another reveal or new fact.",
    },
    {
        "nome": "MIOLO (3 de 3)",
        "minimo": 250, "maximo": 320,
        "pt": "Feche o DESENVOLVIMENTO: o desfecho do conflito e o que "
              "ficou depois dele. Encaixe a última revelação antes da "
              "conclusão.",
        "en": "Close the CORE: how the conflict resolved and what was "
              "left afterwards. Land the last reveal before the "
              "conclusion.",
    },
    {
        "nome": "CONCLUSÃO",
        "minimo": 180, "maximo": 230,
        "pt": "Escreva o FECHAMENTO. Se o assunto ainda está em "
              "andamento, diga o que isso sinaliza pro futuro do setor; "
              "se é caso encerrado, escreva a lição de gestão central. "
              "Termine com uma frase de impacto, específica desta "
              "história - nunca uma frase que caberia em qualquer vídeo.",
        "en": "Write the ENDING. If the story is still unfolding, say "
              "what it signals for the sector's future; if it is closed, "
              "state the central management lesson. Finish with one "
              "striking line specific to THIS story - never a line that "
              "would fit any video.",
    },
)

_REGRAS_COMPACTAS_PT = """REGRAS FIXAS (valem em todo bloco):
- Formato obrigatório: cada frase vira uma linha "NARRAÇÃO:" seguida, na
  LINHA SEGUINTE, de uma linha "VISUAL:" descrevendo a imagem de apoio.
  Nunca junte as duas na mesma linha.
- Marque [VERIFICAR] em todo número específico sobre a empresa real
  (percentual, R$/US$, quantidade, data exata), a menos que seja fato
  amplamente conhecido.
- PROIBIDO inventar pessoa comum com nome próprio. Se precisar de uma
  reação humana, descreva genericamente ("um gerente de loja notou que").
- [ARQUIVO REAL] só pode aparecer numa linha VISUAL, nunca na narração.
- PROIBIDO escrever na narração as palavras "mini-gancho", "bloco",
  "passo", "backstory", "miolo" - são instruções, não texto narrado.
- Frases curtas, linguagem falada. Primeira pessoa do plural quando
  couber ("vamos aos números"), nunca do singular.
- Responda SOMENTE com as linhas NARRAÇÃO:/VISUAL: deste bloco. Sem
  título, sem comentário, sem repetir o que já foi escrito antes."""

_REGRAS_COMPACTAS_EN = """FIXED RULES (apply to every block):
- Mandatory format: each sentence becomes a "NARRAÇÃO:" line followed, on
  the NEXT LINE, by a "VISUAL:" line describing the supporting image.
  Never put both on the same line. Keep those two labels in Portuguese
  exactly as written; the content itself stays in English.
- Mark [VERIFICAR] on every specific number about the real company
  (percentage, R$/US$, quantity, exact date) unless it is a widely known
  fact.
- FORBIDDEN to invent an ordinary person with a proper name. For a human
  reaction, describe it generically ("a store manager noticed that").
- [ARQUIVO REAL] may appear only on a VISUAL line, never in the narration.
- FORBIDDEN to write the words "mini-gancho", "bloco", "passo",
  "backstory", "miolo" in the narration - they are instructions, not
  narrated text.
- Short sentences, spoken language. First person plural where it fits
  ("let's look at the numbers"), never first person singular.
- Answer ONLY with this block's NARRAÇÃO:/VISUAL: lines. No heading, no
  commentary, no repeating what was written before."""


def estimar_duracao(palavras):
    """Palavras de narração -> minutos aproximados de vídeo. É o número
    que responde 'dá pra fazer um vídeo com isso?' antes de gastar
    qualquer coisa nas etapas seguintes."""
    if not palavras:
        return "0min"
    minutos = palavras / PALAVRAS_POR_MINUTO_NARRACAO
    return f"{int(minutos)}min{int((minutos - int(minutos)) * 60):02d}s"


def _resumo_do_que_ja_foi_escrito(roteiro_parcial, limite=1800):
    """O bloco novo precisa saber onde a história parou - mas mandar o
    roteiro inteiro a cada chamada faria o prompt crescer sem parar e
    estourar o contexto no último bloco. Manda só o fim."""
    if not roteiro_parcial:
        return ""
    if len(roteiro_parcial) <= limite:
        return roteiro_parcial
    return "[...início do roteiro omitido...]\n" + roteiro_parcial[-limite:]


def _prompt_do_bloco(bloco, tema, roteiro_parcial, dossie_texto, tentativa_curta=0):
    ingles = GERAR_EM_INGLES
    regras = _REGRAS_COMPACTAS_EN if ingles else _REGRAS_COMPACTAS_PT
    instrucao = bloco["en"] if ingles else bloco["pt"]
    ja_escrito = _resumo_do_que_ja_foi_escrito(roteiro_parcial)

    if ingles:
        partes = [
            f"You are writing ONE BLOCK of a YouTube documentary script "
            f"(business/management niche).\n\nTOPIC: {tema}\n",
            regras,
            f"\nTHIS BLOCK - {bloco['nome']}:\n{instrucao}\n",
            # Alvo declarado como o TOPO da faixa, não como faixa: pedindo
            # "entre X e Y", o modelo ancora no piso e entrega X - com seis
            # blocos assim o roteiro fecha abaixo do mínimo do vídeo.
            f"LENGTH OF THIS BLOCK: aim for {bloco['maximo']} words of "
            f"narration. Anything under {bloco['minimo']} words is too "
            f"short and will be rejected. This is the whole task: do not "
            f"try to write the rest of the video, only this block.",
        ]
        if ja_escrito:
            partes.append(
                f"\nWHAT WAS WRITTEN SO FAR (continue from here, do NOT "
                f"repeat it):\n{ja_escrito}"
            )
        if dossie_texto:
            partes.append(
                f"\nRESEARCH DOSSIER (use only facts from here; anything "
                f"not in it, leave out or write without numbers):\n{dossie_texto}"
            )
        if tentativa_curta:
            partes.append(
                f"\nATTENTION: your previous answer to this same block came "
                f"back with only {tentativa_curta} words, well under the "
                f"{bloco['minimo']} required. Write it again, longer, "
                f"developing the same content with more detail and more "
                f"sentences. Do not add new facts to pad it."
            )
    else:
        partes = [
            f"Você está escrevendo UM BLOCO de um roteiro de vídeo "
            f"documental de YouTube (nicho empresas e administração).\n\n"
            f"TEMA: {tema}\n",
            regras,
            f"\nESTE BLOCO - {bloco['nome']}:\n{instrucao}\n",
            # Ver comentário na versão em inglês: alvo é o topo da faixa.
            f"TAMANHO DESTE BLOCO: escreva perto de {bloco['maximo']} "
            f"palavras de narração. Abaixo de {bloco['minimo']} palavras é "
            f"curto demais e será rejeitado. Essa é a tarefa inteira: não "
            f"tente escrever o resto do vídeo, só este bloco.",
        ]
        if ja_escrito:
            partes.append(
                f"\nO QUE JÁ FOI ESCRITO (continue daqui, NÃO repita):"
                f"\n{ja_escrito}"
            )
        if dossie_texto:
            partes.append(
                f"\nDOSSIÊ DE PESQUISA (use só fatos daqui; o que não "
                f"estiver nele, deixe de fora ou escreva sem número):"
                f"\n{dossie_texto}"
            )
        if tentativa_curta:
            partes.append(
                f"\nATENÇÃO: sua resposta anterior pra este mesmo bloco "
                f"veio com só {tentativa_curta} palavras, bem abaixo das "
                f"{bloco['minimo']} necessárias. Escreva de novo, mais "
                f"longo, desenvolvendo o mesmo conteúdo com mais detalhe e "
                f"mais frases. Não invente fato novo pra encher."
            )
    return "\n".join(partes)


def escrever_roteiro_por_blocos(tema, dossie=None):
    """
    Escreve o roteiro em seis chamadas pequenas em vez de uma grande.

    Cada bloco tem alvo próprio (60 a 350 palavras), que é tamanho que
    modelo pequeno entrega. Bloco que volta curto demais é refeito UMA
    vez, com o número real na cara do modelo - a mesma mecânica do antigo
    passe de expansão, só que sobre 300 palavras em vez de 1.300, que é a
    diferença entre funcionar e não funcionar.

    A contagem aparece a cada bloco: dá pra ver o roteiro crescendo em vez
    de esperar o fim pra descobrir que saiu curto.
    """
    dossie_texto = texto_do_dossie(dossie, PESQUISA_MAX_CHARS_DOSSIE_CURTO) if dossie else ""
    partes = []
    total = 0
    alvo_total = sum(b["minimo"] for b in BLOCOS_DO_ROTEIRO)

    for numero, bloco in enumerate(BLOCOS_DO_ROTEIRO, 1):
        roteiro_parcial = "\n".join(partes)
        # max_tokens dimensionado pro bloco: ~2 tokens por palavra em
        # PT-BR, mais folga pras linhas VISUAL.
        teto_tokens = max(900, bloco["maximo"] * 4)

        texto = chamar_llm(
            _prompt_do_bloco(bloco, tema, roteiro_parcial, dossie_texto),
            temperature=0.8,
            max_tokens=teto_tokens,
            avisar_corte=False,
        )
        palavras = contar_palavras_narracao(texto)

        # Abaixo do mínimo do bloco, refaz - e não "abaixo de 70% do
        # mínimo": com seis blocos entregando 80% cada, o roteiro fecha
        # curto e a rodada inteira do crítico é desperdiçada. Uma chamada
        # extra aqui é mais barata que uma tentativa inteira lá.
        if palavras < bloco["minimo"]:
            print(
                f"    [{numero}/{len(BLOCOS_DO_ROTEIRO)}] {bloco['nome']}: "
                f"{palavras} palavras (curto) - refazendo este bloco..."
            )
            texto_novo = chamar_llm(
                _prompt_do_bloco(bloco, tema, roteiro_parcial, dossie_texto,
                                 tentativa_curta=palavras),
                temperature=0.8,
                max_tokens=teto_tokens,
                avisar_corte=False,
            )
            palavras_novo = contar_palavras_narracao(texto_novo)
            if palavras_novo > palavras:
                texto, palavras = texto_novo, palavras_novo

        texto = texto.strip()
        if texto:
            partes.append(texto)
        total += palavras
        print(
            f"    [{numero}/{len(BLOCOS_DO_ROTEIRO)}] {bloco['nome']}: "
            f"+{palavras} palavras | total {total} "
            f"(~{estimar_duracao(total)} de vídeo)"
        )

    roteiro = "\n".join(partes)
    total_real = contar_palavras_narracao(roteiro)
    print(
        f"  Roteiro montado: {total_real} palavras de narração "
        f"(~{estimar_duracao(total_real)} de vídeo; o alvo dos blocos "
        f"somados é {alvo_total}+)."
    )
    return roteiro


def escrever_roteiro(tema, roteiro_anterior=None, mudancas_obrigatorias=None,
                    historico_mudancas=None, dossie=None):
    # Primeira escrita vai por blocos (ver comentário em
    # escrever_roteiro_por_blocos). As REVISÕES continuam em chamada única:
    # lá o modelo recebe um texto pronto pra corrigir, não precisa produzir
    # 1.400 palavras do zero.
    if roteiro_anterior is None and ESCREVER_POR_BLOCOS:
        return escrever_roteiro_por_blocos(tema, dossie=dossie)

    template = ROTEIRO_PROMPT_EN if GERAR_EM_INGLES else ROTEIRO_PROMPT
    prompt = template.format(tema=tema)
    # Na primeira escrita o dossiê vai inteiro; numa revisão o prompt já
    # carrega o roteiro anterior (até 14k caracteres) mais o histórico de
    # pedidos, então o dossiê entra na versão curta pra não estourar a
    # janela de contexto do modelo local.
    if dossie:
        limite = (
            PESQUISA_MAX_CHARS_DOSSIE_CURTO if roteiro_anterior
            else PESQUISA_MAX_CHARS_DOSSIE
        )
        prompt += bloco_dossie_para_prompt(texto_do_dossie(dossie, limite))
    prompt += gerar_reforco_por_aprendizado()
    if roteiro_anterior and mudancas_obrigatorias:
        prompt += (
            "\n\nJá existe uma versão anterior deste roteiro, que foi REPROVADA "
            "pelo crítico. Sua tarefa agora é REVISAR essa versão, não escrever "
            "outra do zero. Mantenha tudo que já estava bom e mude APENAS o que "
            "está listado como obrigatório abaixo - se um trecho não foi citado "
            "no apontamento, deixe ele como está.\n\n"
            f"VERSÃO ANTERIOR (revise a partir dela):\n"
            f"{_truncar(roteiro_anterior, 14000, 'roteiro anterior')}\n\n"
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
            # Cada item é truncado individualmente: o histórico cresce a
            # cada tentativa, então é aqui que a soma estourava o contexto.
            historico_formatado = "\n---\n".join(
                f"Tentativa {i}: {_truncar(m, 1200, 'pedido')}"
                for i, m in enumerate(historico_mudancas, 1)
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

def avaliar_roteiro(roteiro, mudancas_pedidas_antes=None, dossie=None):
    template = AVALIACAO_PROMPT_EN if GERAR_EM_INGLES else AVALIACAO_PROMPT
    # O roteiro vai inteiro pro prompt, e foi aqui que a API recusou o
    # pedido com 'context_length_exceeded' quando um roteiro veio
    # gigante/duplicado. Um roteiro legítimo desse canal tem ~1300-1600
    # palavras (uns 12k caracteres com as linhas VISUAL), então 20k dá
    # folga confortável e ainda barra o caso patológico.
    prompt = template.format(roteiro=_truncar(roteiro, 20000, "roteiro"))
    if dossie:
        # Com o dossiê em mãos o campo "EVENTO SEM VERIFICAR" deixa de ser
        # um chute: dá pra dizer se aquele evento existe no material
        # levantado ou se o roteiro inventou.
        prompt += (
            "\n\nDOSSIÊ USADO PELO ROTEIRISTA (fontes abertas, levantado "
            "antes da escrita):\n"
            f"{texto_do_dossie(dossie, PESQUISA_MAX_CHARS_DOSSIE_CURTO)}\n\n"
            "COMO ISSO MUDA SUA AVALIAÇÃO: evento que aparece no dossiê "
            "está respaldado - não liste em EVENTO SEM VERIFICAR só por "
            "não ter marcador. Evento que NÃO aparece no dossiê e não é "
            "de conhecimento público amplo é o caso grave: provavelmente "
            "foi inventado, e aí sim entra no campo. O dossiê pode estar "
            "incompleto, então na dúvida prefira mandar marcar [VERIFICAR] "
            "a mandar apagar o trecho."
        )
    if mudancas_pedidas_antes and not mudancas_sao_vazias(mudancas_pedidas_antes):
        prompt += (
            "\n\nCONTEXTO: na rodada de avaliação ANTERIOR, você (ou outra "
            "avaliação deste mesmo roteiro) pediu estas mudanças:\n"
            f"{_truncar(mudancas_pedidas_antes, 3000, 'pedido anterior')}\n\n"
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


def _truncar(texto, limite_caracteres, rotulo="trecho"):
    """
    Corta um texto que vai ser REINJETADO num prompt. Existe por causa de
    um estouro real de contexto: o prompt do roteirista recebe de volta o
    roteiro anterior + as mudanças pedidas + o histórico de TODAS as
    rodadas, e o do crítico recebe o roteiro inteiro. Sem teto, cada
    tentativa cresce sobre a anterior até a API recusar o pedido todo com
    'context_length_exceeded' - foi exatamente o que aconteceu na 3ª
    tentativa de um refazer. Cortar um pedaço do contexto é ruim; abortar
    a execução inteira é pior.
    """
    if not texto or len(texto) <= limite_caracteres:
        return texto
    cortado = texto[:limite_caracteres]
    return (
        f"{cortado}\n\n[...{rotulo} cortado aqui - tinha {len(texto)} "
        f"caracteres, ficou nos primeiros {limite_caracteres} pra não "
        "estourar o limite de contexto do modelo]"
    )


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
    em vez de mandar a avaliação inteira de volta pro roteirista.

    O fallback (quando o crítico não segue o template) é TRUNCADO de
    propósito: antes ele devolvia a avaliação inteira, que ia pro prompt
    do roteirista E pro histórico acumulado de todas as rodadas - três ou
    quatro tentativas assim estouravam o contexto do modelo e derrubavam
    a execução com 'context_length_exceeded'.
    """
    # Para no PRÓXIMO campo do template, seja ele qual for. Parar só no
    # VEREDITO funcionava enquanto o modelo mantinha a ordem do template -
    # quando ele troca a ordem, o campo seguinte inteiro vinha junto e
    # virava "mudança obrigatória" que o roteirista não sabe executar.
    proximo_campo = "|".join(
        _padrao_rotulo(campo)
        for campo in _CAMPOS_PROBLEMA_APRENDIZADO
        + ("VEREDITO", "CHANCE DE RETENÇÃO", "NOTA DO GANCHO",
           "PONTOS DE QUEDA", "FECHO", "MOTIVO")
    )
    match = re.search(
        _padrao_rotulo("MUDANÇAS OBRIGATÓRIAS")
        + r"(.+?)(?:\n(?:" + proximo_campo + r")|\Z)",
        avaliacao_texto,
        re.DOTALL,
    )
    if match:
        return _truncar(match.group(1).strip(), 3000, "lista de mudanças")
    # Fallback: o crítico não seguiu o template. Manda a avaliação, mas
    # CORTADA - devolver o texto inteiro aqui era o começo da bola de neve
    # que estourava o contexto depois de 3-4 tentativas.
    return _truncar(avaliacao_texto, 3000, "avaliação (template não seguido)")


def avaliacao_segue_template(avaliacao_texto):
    """
    O crítico devolveu uma avaliação de verdade, ou devolveu outra coisa?

    Modelo pequeno às vezes ignora o template e responde qualquer coisa -
    num ensaio do pipeline ele devolveu um ROTEIRO no lugar da avaliação.
    Sem esta checagem, o texto inteiro virava "mudanças obrigatórias"
    (pelo fallback de extrair_mudancas_obrigatorias) e ia parar no prompt
    do roteirista, que passava a tentar "corrigir" um pedido que não era
    pedido nenhum - e o loop reprovava de novo, sempre igual.

    Dois sinais bastam: a linha do veredito e pelo menos dois nomes de
    campo do template.
    """
    if not avaliacao_texto or len(avaliacao_texto.strip()) < 40:
        return False
    tem_veredito = bool(re.search(
        _padrao_rotulo("VEREDITO") + r"(APROVADO|REPROVADO)",
        avaliacao_texto, re.IGNORECASE,
    ))
    campos_achados = sum(
        1 for campo in _CAMPOS_PROBLEMA_APRENDIZADO + ("MUDANÇAS OBRIGATÓRIAS", "CHANCE DE RETENÇÃO")
        if re.search(_padrao_rotulo(campo), avaliacao_texto)
    )
    return tem_veredito and campos_achados >= 2


def extrair_veredito(avaliacao_texto):
    """Lê a linha 'VEREDITO:' do template fixo de avaliação."""
    match = re.search(
        _padrao_rotulo("VEREDITO") + r"(APROVADO|REPROVADO)",
        avaliacao_texto,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).lower()
    # modelo pequeno pode não seguir o template à risca - fallback simples
    return "aprovado" if "aprovado" in avaliacao_texto.lower()[-200:] else "reprovado"


def _campo_indica_problema(valor_bruto):
    """
    Cada campo do template tem uma forma diferente de dizer 'sem problema'
    ("Nenhum encontrado", "Todos os blocos têm mini-gancho", "Nenhuma
    encontrada") - normaliza tudo isso numa checagem só.
    """
    valor = valor_bruto.strip().strip("*_# ").lower()
    if not valor:
        return False
    frases_vazias = (
        "nenhum", "nenhuma", "todos os blocos têm mini-gancho",
        "todos os blocos tem mini-gancho", "none", "n/a", "-",
    )
    return not any(valor.startswith(f) for f in frases_vazias)


def registrar_aprendizado(avaliacao_texto):
    """
    Depois de CADA avaliação (aprovada ou não), extrai quais campos
    tiveram problema real e acumula num arquivo ao lado do script - esse
    histórico sobrevive entre execuções diferentes, então o pipeline vai
    "lembrando" quais erros o crítico mais aponta ao longo de vários
    vídeos, não só dentro de uma execução.
    """
    if CAMINHO_ESTATISTICAS_APRENDIZADO.exists():
        try:
            with open(CAMINHO_ESTATISTICAS_APRENDIZADO, "r", encoding="utf-8") as f:
                stats = json.load(f)
        except (json.JSONDecodeError, OSError):
            stats = {}
    else:
        stats = {}

    stats.setdefault("total_avaliacoes", 0)
    stats.setdefault("problemas", {c: 0 for c in _CAMPOS_PROBLEMA_APRENDIZADO})
    stats["total_avaliacoes"] += 1

    for campo in _CAMPOS_PROBLEMA_APRENDIZADO:
        match = re.search(_padrao_rotulo(campo) + r"(.+)", avaliacao_texto)
        if match and _campo_indica_problema(match.group(1)):
            stats["problemas"][campo] = stats["problemas"].get(campo, 0) + 1

    with open(CAMINHO_ESTATISTICAS_APRENDIZADO, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    return stats


def gerar_reforco_por_aprendizado(limiar=0.4, minimo_avaliacoes=3):
    """
    Olha o histórico acumulado e, se algum problema aparece em uma fatia
    alta das avaliações passadas (padrão: 40%, com pelo menos 3 vídeos
    avaliados pra não reagir a coincidência de amostra pequena), devolve
    um texto extra pra reforçar exatamente esse ponto no próximo roteiro -
    ANTES de virar reclamação repetida de novo.
    """
    if not CAMINHO_ESTATISTICAS_APRENDIZADO.exists():
        return ""
    try:
        with open(CAMINHO_ESTATISTICAS_APRENDIZADO, "r", encoding="utf-8") as f:
            stats = json.load(f)
    except (json.JSONDecodeError, OSError):
        return ""

    total = stats.get("total_avaliacoes", 0)
    if total < minimo_avaliacoes:
        return ""

    # "NÚMEROS SEM VERIFICAR" sai do reforço: quem resolve isso agora é
    # marcar_verificar_automatico(), no código, com 100% de acerto.
    # Continuar gritando no prompt sobre o problema já resolvido só rouba
    # atenção do modelo dos pontos que ainda dependem dele.
    campos_ja_resolvidos_no_codigo = ("NÚMEROS SEM VERIFICAR",)

    candidatos = []
    for campo, contagem in stats.get("problemas", {}).items():
        if campo in campos_ja_resolvidos_no_codigo:
            continue
        taxa = contagem / total
        if taxa >= limiar:
            candidatos.append((taxa, campo, contagem))

    # No máximo 3, dos mais frequentes pros menos: lista longa de "preste
    # atenção" vira ruído e o modelo pequeno acaba não priorizando nada.
    candidatos.sort(reverse=True)
    reforcos = [
        f"- '{campo}' apareceu em {contagem} de {total} vídeos "
        f"anteriores ({taxa * 100:.0f}%) - preste atenção redobrada "
        "nisso especificamente antes de entregar."
        for taxa, campo, contagem in candidatos[:3]
    ]

    if not reforcos:
        return ""

    return (
        "\n\nAVISO BASEADO NO HISTÓRICO (padrão de erro acumulado dos "
        f"últimos {total} vídeos deste canal, não só desta execução):\n"
        + "\n".join(reforcos)
    )


# =========================================================================
# CORREÇÃO MECÂNICA - o que o código consegue resolver sozinho, o prompt
# não precisa pedir
# =========================================================================
# Por que esta seção existe: o histórico de aprendizado mostrou
# "NÚMEROS SEM VERIFICAR" em 15 de 17 avaliações (88%). Ou seja: a regra
# mais repetida do prompt do roteirista era justamente a que o modelo
# menos conseguia cumprir - e cada falha dessas custava uma tentativa
# INTEIRA do loop (roteiro + crítica), sem nunca convergir: o crítico
# listava os mesmos números na tentativa 2 e na 3, palavra por palavra.
#
# Só que "colocar [VERIFICAR] do lado de todo número específico" não é
# uma tarefa de julgamento, é uma tarefa de texto. Regex faz isso com
# 100% de acerto e custo zero. O modelo passa a ser cobrado só pelo que
# de fato depende dele (estrutura, gancho, ritmo, não inventar enredo).
#
# Marcar de MAIS aqui é inofensivo de propósito: o marcador é removido
# de qualquer forma em extrair_narracao_limpa() antes do áudio, então
# ele nunca chega no ElevenLabs - o efeito prático é só a sua revisão
# manual ficar com mais itens conferidos, que é exatamente o aviso
# permanente deste projeto ("revise todo [VERIFICAR] em fonte primária").

# Ordem das alternativas importa: a primeira que casa vence, então as
# formas longas (R$ 1,2 bilhão) vêm antes das curtas (1,2).
# ATENÇÃO à ordem das unidades: "milhões" TEM que vir antes de "mil",
# senão o regex casa só o "mil" de "milhões" e o marcador entra no meio
# da palavra ("US$ 400 mil [VERIFICAR]hões"). Regex alterna da esquerda
# pra direita e aceita o primeiro que casar, não o mais longo.
_UNIDADES_DE_ESCALA = (
    r"(?:milh(?:ão|ões|ao|oes)|bilh(?:ão|ões|ao|oes)|"
    r"trilh(?:ão|ões|ao|oes)|million|billion|trillion|thousand|mil)"
)

_PADRAO_NUMERO_ESPECIFICO = re.compile(
    r"(?:R\$|US\$|U\$|USD|BRL|\$|€)\s?\d[\d.,]*"
    r"(?:\s?" + _UNIDADES_DE_ESCALA + r")?\b"
    r"|\d[\d.,]*\s?(?:%|por\s?cento|percent)"
    r"|\d[\d.,]*\s?" + _UNIDADES_DE_ESCALA + r"\b"
    r"|\b(?:1[5-9]\d{2}|20\d{2})\b"
    r"|\b\d{1,3}(?:[.,]\d{3})+\b"
    r"|\b\d{3,}\b",
    re.IGNORECASE,
)

_INICIO_LINHA_NARRACAO = re.compile(r"^[\s*#>\-]*NARRA[ÇC][ÃA]O\s*:", re.IGNORECASE)

# Distância (em caracteres) dentro da qual um [VERIFICAR] que o próprio
# roteirista escreveu já conta como "do lado" do número - evita marcar
# duas vezes a mesma coisa.
_RAIO_DO_MARCADOR = 30

# Dois números que formam UMA expressão só ("entre 2015 e 2019", "de 24%
# para 30%", "R$ 4 bilhões a R$ 5 bilhões") dividem um marcador - dois
# seguidos ali só poluiriam a linha. O teste é o que existe ENTRE eles:
# se for só conectivo/pontuação, é a mesma expressão; se tiver qualquer
# outra palavra ("em 2015, faturou R$ 2,5 bilhões"), são alegações
# diferentes e cada uma leva o seu marcador.
_LIGACAO_ENTRE_NUMEROS = re.compile(
    r"[\s,]*(?:e|a|ou|até|ate|para|and|to|or|-|–|—|/)?[\s,]*",
    re.IGNORECASE,
)


def marcar_verificar_automatico(roteiro):
    """
    Percorre só as linhas NARRAÇÃO e coloca [VERIFICAR] ao lado de todo
    número específico (percentual, R$/US$, escala, ano, quantidade grande)
    que ainda não tenha um marcador perto. Devolve (roteiro, quantidade
    marcada).

    Não toca em linha VISUAL - lá o número faz parte da descrição da
    imagem, não é alegação factual narrada. Se NARRAÇÃO e VISUAL vierem
    grudados na mesma linha (acontece quando o modelo erra o formato),
    corta no "VISUAL:" e só marca a parte narrada.
    """
    if not roteiro:
        return roteiro, 0

    marcados = 0
    linhas_saida = []
    for linha in roteiro.splitlines():
        if not _INICIO_LINHA_NARRACAO.match(linha):
            linhas_saida.append(linha)
            continue

        corte = linha.upper().find("VISUAL:")
        parte_narrada = linha if corte == -1 else linha[:corte]
        resto_da_linha = "" if corte == -1 else linha[corte:]

        pedacos = []
        ultimo_fim = 0
        ultima_marca = None
        for achado in _PADRAO_NUMERO_ESPECIFICO.finditer(parte_narrada):
            vizinhanca = parte_narrada[
                max(0, achado.start() - _RAIO_DO_MARCADOR):
                achado.end() + _RAIO_DO_MARCADOR
            ]
            if "[VERIFICAR]" in vizinhanca:
                continue
            if ultima_marca is not None and _LIGACAO_ENTRE_NUMEROS.fullmatch(
                parte_narrada[ultima_marca:achado.start()]
            ):
                continue
            pedacos.append(parte_narrada[ultimo_fim:achado.end()])
            pedacos.append(" [VERIFICAR]")
            ultimo_fim = achado.end()
            ultima_marca = achado.end()
            marcados += 1
        pedacos.append(parte_narrada[ultimo_fim:])
        linhas_saida.append("".join(pedacos) + resto_da_linha)

    return "\n".join(linhas_saida), marcados


def _padrao_rotulo(nome):
    """
    Monta o regex de um rótulo do template do crítico tolerando o que
    modelo pequeno faz com formatação: markdown em volta
    ("**MUDANÇAS OBRIGATÓRIAS:**"), acento comido ("MUDANCAS
    OBRIGATORIAS:") e espaço a mais. Sem isso, uma estrela perdida fazia
    a extração cair no fallback e mandar a AVALIAÇÃO INTEIRA de volta pro
    roteirista como se fosse a lista de mudanças - que é como o loop
    começava a girar em falso.
    """
    partes = []
    for caractere in nome:
        if caractere == " ":
            partes.append(r"\s+")
            continue
        base = unicodedata.normalize("NFD", caractere)[0]
        if base != caractere and base.isalpha():
            partes.append(f"[{caractere}{base}]")
        else:
            partes.append(re.escape(caractere))
    # O rabicho aceita as duas ordens que aparecem na prática:
    # "**CAMPO:** valor" (markdown, espaço) e "CAMPO: **valor**".
    return r"[*_#>\s]*" + "".join(partes) + r"[*_#\s]*:[ \t]*[*_#]*[ \t]*"


# Marcas de SUGESTÃO: se o item começa assim, o próprio crítico está
# dizendo que aquilo é opinião, não requisito. Isso não pode reprovar um
# roteiro - "Considerar a possibilidade de adicionar mini-ganchos" já
# travou tentativa de roteiro bom aqui.
_MARCAS_DE_SUGESTAO = (
    "considerar", "considere", "considerando", "poderia", "poderiam",
    "talvez", "sugiro", "sugere-se", "sugestao", "sugestão", "recomenda-se",
    "recomendo", "seria bom", "seria interessante", "seria ideal",
    "se possivel", "se possível", "opcional", "idealmente", "avaliar se",
    "consider", "could ", "might ", "optionally", "optional",
    "suggest", "it would be", "ideally", "nice to have", "perhaps",
)

# Pedidos que o roteirista NÃO tem como executar: ele não pesquisa, não
# abre fonte, não confirma nada. "Verificar a veracidade dos eventos"
# reprovava o roteiro pra sempre porque nenhuma revisão conseguia
# satisfazer o pedido. O que o roteirista PODE fazer é marcar - então o
# item é reescrito pra isso, em vez de virar um bloqueio eterno.
_PEDIDOS_DE_PESQUISA = (
    "veracidade", "verificar a autenticidade", "confirmar a fonte",
    "confirmar as fontes", "consultar fontes", "buscar fontes",
    "checar as fontes", "pesquisar", "pesquise", "fact-check", "fact check",
    "verify the truth", "verify the accuracy", "verify the veracity",
    "confirm the accuracy", "research ", "look up",
)

_ACAO_MARCAR_EVENTOS = (
    "Adicione [VERIFICAR] ao lado de cada EVENTO narrativo que não seja "
    "de conhecimento público amplo (processo, investigação, relatório, "
    "vídeo viral, reunião de diretoria, decisão interna, mudança de "
    "política). Você NÃO precisa pesquisar nem confirmar nada - basta "
    "marcar o trecho na própria linha NARRAÇÃO."
)

# Palavras que sobram numa lista de números e não contam como instrução.
_PALAVRAS_SEM_INSTRUCAO = {
    "de", "do", "da", "dos", "das", "e", "em", "no", "na", "nos", "nas",
    "por", "cento", "reais", "real", "dolares", "dólares", "mil",
    "milhao", "milhão", "milhoes", "milhões", "bilhao", "bilhão",
    "bilhoes", "bilhões", "trilhao", "trilhão", "trilhoes", "trilhões",
    "ano", "anos", "pessoas", "usuarios", "usuários", "clientes",
    "compradores", "vendedores", "funcionarios", "funcionários",
    "lojas", "unidades", "r", "us", "usd", "brl", "the", "of", "and",
    "in", "to", "million", "billion", "thousand", "trillion", "users",
    "people", "buyers", "sellers", "years", "year", "customers",
    "employees", "stores",
}


def _item_e_lista_solta(item):
    """
    Detecta o item que não é uma mudança, é só uma lista de dados
    copiada de outro campo - foi literalmente a reprovação das tentativas
    2 e 3 do seu run: "[2.5 bilhões de reais], [1.2 bilhões de reais],
    [24%], [2015], [2019]...". Isso chega no roteirista sem nenhum verbo,
    ele não tem como saber o que fazer, devolve o mesmo roteiro, o
    crítico reprova igual - e a tentativa foi jogada fora.
    """
    if not _PADRAO_NUMERO_ESPECIFICO.search(item):
        return False
    resto = _PADRAO_NUMERO_ESPECIFICO.sub(" ", item)
    resto = re.sub(r"[\[\]\(\)\{\},;:.\-–—/%$€*]", " ", resto)
    palavras = [
        p for p in resto.split()
        if p.isalpha() and p.lower() not in _PALAVRAS_SEM_INSTRUCAO
    ]
    return len(palavras) <= 2


def _pedido_ja_atendido(item, roteiro):
    """
    O crítico está pedindo [VERIFICAR] em número que o código JÁ marcou?

    Acontece de verdade: num run real o pipeline marcou 8 números e o
    crítico devolveu "Add [VERIFICAR] next to 2015, 2024, 375" mesmo com
    os três marcados no texto. Modelo de 7B lê mal marcador no meio da
    frase. Sem esta checagem, o roteirista recebe uma ordem impossível de
    cumprir (já está feito), devolve o mesmo roteiro, e a tentativa vira
    lixo - exatamente o ciclo que a trava de repetição tenta cortar, só
    que uma rodada tarde demais.

    Conservador de propósito: só descarta se TODA ocorrência de TODO
    número citado já estiver marcada. Se algum número do pedido nem
    aparece no roteiro, mantém o pedido.
    """
    if not roteiro or "[VERIFICAR]" not in item.upper():
        return False
    numeros = [achado.group(0) for achado in _PADRAO_NUMERO_ESPECIFICO.finditer(item)]
    if not numeros:
        return False

    linhas_narradas = [
        linha for linha in roteiro.splitlines()
        if _INICIO_LINHA_NARRACAO.match(linha)
    ]
    achou_alguma_ocorrencia = False
    for numero in numeros:
        for linha in linhas_narradas:
            posicao = linha.find(numero)
            while posicao != -1:
                achou_alguma_ocorrencia = True
                vizinhanca = linha[
                    max(0, posicao - _RAIO_DO_MARCADOR):
                    posicao + len(numero) + _RAIO_DO_MARCADOR
                ]
                if "[VERIFICAR]" not in vizinhanca:
                    return False
                posicao = linha.find(numero, posicao + 1)
    return achou_alguma_ocorrencia


def _pedido_quebra_regra_do_canal(comparavel):
    """
    Pedido que contraria uma regra fixa do canal não pode reprovar o
    roteiro - se aceito, vira loop infinito: o roteirista cumpre a regra,
    o crítico exige o contrário, sempre.

    O caso real: "Name the company 'Sabesp' in the opening lines". A
    introdução esconde o nome da empresa DE PROPÓSITO (é o gancho); a
    regra é nomear no corpo do texto. Atender isso quebraria o vídeo.
    """
    fala_em_nomear = any(v in comparavel for v in (
        "nomear", "nomeie", "cite o nome", "citar o nome", "mencione o nome",
        "revele o nome", "name the company", "mention the name",
        "reveal the name", "state the company",
    ))
    fala_em_abertura = any(v in comparavel for v in (
        "introducao", "abertura", "gancho", "primeiras linhas",
        "primeiras frases", "opening", "intro", "first lines",
        "first sentences", "beginning",
    ))
    return fala_em_nomear and fala_em_abertura


def _normalizar_para_comparar(texto):
    """Minúsculas, sem acento e sem pontuação - pra comparar dois pedidos
    do crítico e saber se são o mesmo pedido escrito de outro jeito."""
    decomposto = unicodedata.normalize("NFD", texto.lower())
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", sem_acento).strip()


def _dividir_em_itens(mudancas_texto):
    """Quebra a lista do crítico em itens, aceitando bullet de traço,
    asterisco, bolinha ou numeração."""
    itens = []
    for linha in mudancas_texto.splitlines():
        limpa = re.sub(r"^\s*(?:[-*•–—]|\d+[.)])\s*", "", linha).strip()
        if limpa:
            itens.append(limpa)
    return itens


def filtrar_mudancas_acionaveis(mudancas_texto, roteiro=None):
    """
    Transforma a lista do crítico em pedidos que o roteirista consegue de
    fato executar, e devolve (texto_acionavel, itens_descartados) - cada
    descartado é {"item", "motivo"}.

    Cinco tratamentos:
      1. lista solta de números -> vira uma ORDEM ("adicione [VERIFICAR]
         ao lado destes números"), em vez de chegar sem verbo nenhum;
      2. pedido de pesquisa ("verifique a veracidade") -> vira a única
         ação equivalente que o roteirista tem: marcar [VERIFICAR];
      3. sugestão ("considere", "seria bom") -> sai da lista obrigatória.
         Continua contando no aprendizado e continua aparecendo no
         relatório, só não reprova mais o roteiro sozinha;
      4. pedido de [VERIFICAR] em número que o código já marcou -> sai,
         porque não há o que fazer (ver _pedido_ja_atendido);
      5. pedido que contraria regra fixa do canal, tipo nomear a empresa
         na introdução -> sai (ver _pedido_quebra_regra_do_canal).

    Se depois disso não sobrar nada, o roteiro não tinha nenhuma mudança
    obrigatória de verdade - e o chamador trata como aprovado.
    """
    if not mudancas_texto or mudancas_sao_vazias(mudancas_texto):
        return "", []

    acionaveis = []
    descartados = []
    ja_vistos = set()
    for item in _dividir_em_itens(mudancas_texto):
        comparavel = _normalizar_para_comparar(item)
        if not comparavel or comparavel in ("nenhuma", "nenhum"):
            continue

        if _pedido_ja_atendido(item, roteiro):
            descartados.append({
                "item": item,
                "motivo": "já atendido - o código marcou esses números automaticamente",
            })
            continue

        if _pedido_quebra_regra_do_canal(comparavel):
            descartados.append({
                "item": item,
                "motivo": "contraria regra do canal (a introdução não revela o nome da empresa)",
            })
            continue

        if _item_e_lista_solta(item):
            item = (
                "Adicione [VERIFICAR] na própria linha NARRAÇÃO, ao lado de "
                f"cada um destes dados: {item}"
            )
        elif any(p in comparavel for p in _PEDIDOS_DE_PESQUISA):
            item = _ACAO_MARCAR_EVENTOS
        elif any(comparavel.startswith(m) or f" {m}" in f" {comparavel}"
                 for m in _MARCAS_DE_SUGESTAO):
            descartados.append({"item": item, "motivo": "sugestão, não requisito"})
            continue

        chave = _normalizar_para_comparar(item)
        if chave in ja_vistos:
            continue
        ja_vistos.add(chave)
        acionaveis.append(item)

    texto = "\n".join(f"- {i}" for i in acionaveis)
    return _truncar(texto, 3000, "lista de mudanças"), descartados


def assinatura_do_pedido(mudancas_texto):
    """
    Impressão digital de um pedido do crítico, insensível a ordem e a
    reescrita superficial. Serve pra detectar o loop travado: quando a
    reprovação da tentativa N é a MESMA da tentativa N-1, insistir mais
    uma rodada só queima tempo (e cota) - tentativas 2 e 3 do seu run
    vieram idênticas, caractere por caractere.
    """
    if not mudancas_texto:
        return ""
    return " ".join(sorted(set(_normalizar_para_comparar(mudancas_texto).split())))


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


def _slugificar(texto, tamanho_max=40):
    """Transforma o termo de busca num nome de arquivo seguro (sem acento,
    sem espaço, sem caractere especial)."""
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-zA-Z0-9]+", "_", texto).strip("_").lower()
    return texto[:tamanho_max] or "clipe"


def _plano_a_partir_de_dict_antigo(broll_dict):
    """Converte o formato antigo ({texto_visual: resultados}) na lista de
    segmentos. Serve pra abrir na interface os JSON salvos antes desta
    mudança, sem precisar regerar o vídeo."""
    plano = []
    for indice, (visual, dados) in enumerate(broll_dict.items(), 1):
        arquivo_real = isinstance(dados, dict) and dados.get("tipo") == "arquivo_real_necessario"
        plano.append({
            "indice": indice,
            "narracao": "",
            "visual": visual,
            "arquivo_real": arquivo_real,
            "fonte": "arquivo_real" if arquivo_real else "pexels",
            "arquivo": None,
            "resultados_pexels": [] if arquivo_real else (dados or []),
        })
    return plano


def baixar_broll(plano, pasta_destino, por_termo=1):
    """
    Baixa os clipes de b-roll encontrados pra uma pasta local, prontos pra
    arrastar direto no editor de vídeo - em vez de só listar o link, que
    exigia abrir um por um manualmente.

    por_termo=1 baixa só o melhor resultado de cada trecho do roteiro
    (mais rápido). Aumente pra 2 ou 3 se quiser opções pra escolher
    visualmente qual encaixa melhor antes de editar.

    Retorna (baixados, pulados) - duas listas pra você ver o que faltou.

    Recebe a LISTA de segmentos de montar_plano_de_broll(). Aceita também
    o dicionário do formato antigo, pra abrir vídeo salvo antes da
    mudança.
    """
    if isinstance(plano, dict):
        plano = _plano_a_partir_de_dict_antigo(plano)

    pasta_destino.mkdir(parents=True, exist_ok=True)
    baixados = []
    pulados = []

    for segmento in plano:
        i = segmento["indice"]
        termo = segmento["visual"] or segmento["narracao"][:60]
        if segmento["fonte"] == "ia":
            # Já tem (ou vai ter) ilustração - não é caso de baixar clipe.
            continue
        if segmento["fonte"] == "arquivo_real":
            pulados.append((termo, "precisa de arquivo real, não é banco de stock"))
            continue
        dados = segmento.get("resultados_pexels") or []
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
                if j == 1:
                    segmento["arquivo"] = nome_arquivo
            except Exception as e:
                pulados.append((termo, f"erro ao baixar ({type(e).__name__})"))

    print(f"    {len(baixados)} clipe(s) baixado(s), {len(pulados)} pulado(s).")
    return baixados, pulados


# =========================================================================
# AGENTE 4B - B-ROLL ILUSTRADO (imagem gerada por IA)
# =========================================================================
# Por que existe: o Pexels cobre bem o genérico (cidade, escritório,
# gráfico, mãos digitando) e não cobre nada do específico - "o dono da
# loja olhando a planilha de despesas às 23h" não existe em banco de
# stock. Hoje esses trechos são marcados [ARQUIVO REAL] pelo roteirista e
# ficam SEM imagem nenhuma (montar_plano_de_broll pulava a busca). São
# exatamente as cenas que a ilustração resolve.
#
# CONSISTÊNCIA DE PERSONAGEM SEM IMAGEM DE REFERÊNCIA: no estilo deste
# canal o personagem não tem rosto - é um círculo com dois pontos e um
# traço. Quem identifica o mesmo personagem entre duas cenas é a ROUPA e
# o estilo, não a face. Então uma ficha em TEXTO, repetida em toda
# chamada, sustenta a consistência quase tão bem quanto uma referência
# visual - e é o que permite usar gerador gratuito, já que nenhum dos
# gratuitos aceita imagem de referência.

ESTILO_IMAGEM_IA = (
    "Minimalist webtoon-style illustration, characters with simple "
    "circular heads, dot eyes, thin line mouth, flat stick-figure-style "
    "bodies wearing detailed clothing, thick black outlines, flat "
    "cel-shaded coloring, muted desaturated color palette, subtle grainy "
    "paper texture, highly detailed realistic background environment, "
    "digital illustration, comic panel style"
)

# Sinais de cena GENÉRICA - o Pexels cobre bem e de graça, não faz sentido
# gastar geração de imagem nisso.
PALAVRAS_FORCAM_PEXELS = (
    "b-roll genérico", "b-roll generico", "cidade", "trânsito", "transito",
    "skyline", "prédio", "predio", "fachada", "gráfico", "grafico",
    "tela", "monitor", "dinheiro", "cédula", "cedula", "moeda", "esteira",
    "fábrica", "fabrica", "galpão", "galpao", "porto", "contêiner",
    "conteiner", "caminhão", "caminhao", "estrada", "multidão", "multidao",
    "teclado", "mãos digitando", "maos digitando", "aperto de mão",
)

# Sinais de cena ESPECÍFICA da história - é o que o banco de stock não
# tem e a ilustração resolve.
PALAVRAS_FORCAM_IA = (
    "arquivo real", "personagem", "dono", "gerente", "funcionário",
    "funcionario", "cliente", "vendedor", "atendente", "sozinho",
    "olhando", "percebe", "descobre", "conta", "confere", "assina",
    "discute", "reunião de diretoria", "reuniao de diretoria", "decisão",
    "decisao", "madrugada", "de noite", "expressão", "expressao",
    "reação", "reacao", "planilha", "caderno", "anotação", "anotacao",
)


def _tem_palavra(texto, palavras):
    alvo = _normalizar_para_comparar(texto)
    return any(_normalizar_para_comparar(p) in alvo for p in palavras)


def classificar_fonte_do_trecho(narracao, visual):
    """
    Decide de onde vem a imagem deste trecho: "ia" ou "pexels".

    Ordem: [ARQUIVO REAL] sempre vai pra ilustração (é a definição de
    cena que stock não cobre); depois as listas configuráveis; e o padrão
    é Pexels, porque vídeo real de graça é melhor que imagem parada paga
    quando os dois servem.
    """
    if "[ARQUIVO REAL]" in visual.upper() or "ARQUIVO REAL" in visual.upper():
        return "ia"
    if _tem_palavra(visual, PALAVRAS_FORCAM_PEXELS):
        return "pexels"
    if _tem_palavra(visual, PALAVRAS_FORCAM_IA) or _tem_palavra(narracao, PALAVRAS_FORCAM_IA):
        return "ia"
    return "pexels"


def _aplicar_teto_de_ilustracoes(plano):
    """
    TETO_PROPORCAO_IA é limite, não cota: nunca empurra trecho pra IA só
    pra bater uma porcentagem - isso geraria imagem paga pra cena que o
    Pexels já cobria bem. Só rebaixa o excedente de volta pro Pexels,
    começando pelos que NÃO são [ARQUIVO REAL] (esses são os que mais
    precisam da ilustração, então são os últimos a perder a vaga).
    """
    indices_ia = [s["indice"] for s in plano if s["fonte"] == "ia"]
    teto = max(1, int(len(plano) * TETO_PROPORCAO_IA))
    teto = min(teto, MAX_AI_IMAGES_PER_VIDEO)
    if len(indices_ia) <= teto:
        return plano

    def prioridade(segmento):
        # menor = mais importante manter como ilustração
        return 0 if segmento.get("arquivo_real") else 1

    candidatos = sorted(
        [s for s in plano if s["fonte"] == "ia"],
        key=lambda s: (prioridade(s), s["indice"]),
    )
    for segmento in candidatos[teto:]:
        segmento["fonte"] = "pexels"
        segmento["motivo_fonte"] = (
            f"rebaixado pro Pexels - passou do teto de {teto} ilustrações "
            f"({TETO_PROPORCAO_IA:.0%} dos trechos ou MAX_AI_IMAGES_PER_VIDEO)"
        )
    print(
        f"    Teto de ilustrações: {len(indices_ia)} trechos elegíveis, "
        f"{teto} mantidos na IA, o resto volta pro Pexels."
    )
    return plano


def parear_narracao_e_visual(roteiro):
    """
    Devolve os trechos do roteiro pareados: cada linha NARRAÇÃO com a
    linha VISUAL que vem depois dela.

    Existe porque a estrutura antiga era um DICIONÁRIO indexado pelo texto
    da linha VISUAL - e "b-roll genérico de escritório" se repete várias
    vezes num roteiro (o próprio prompt do roteirista usa isso como
    exemplo). Trechos diferentes com o mesmo VISUAL colapsavam numa
    entrada só: o manifest não conseguia representá-los, e o download
    trazia um arquivo para os dois.
    """
    trechos = re.findall(
        r"NARRAÇÃO:\s*(.*?)\s*(?:\n\s*VISUAL:\s*(.*?))?\s*(?=\nNARRAÇÃO:|\Z)",
        roteiro,
        re.DOTALL,
    )
    segmentos = []
    for narracao, visual in trechos:
        narracao = re.sub(r"\s+", " ", narracao).strip()
        visual = re.sub(r"\s+", " ", (visual or "")).strip()
        if not narracao:
            continue
        segmentos.append({
            "indice": len(segmentos) + 1,
            "narracao": narracao,
            "visual": visual,
        })
    return segmentos


def montar_plano_de_broll(roteiro):
    """
    Substitui montar_lista_broll(). Devolve uma LISTA de segmentos, um por
    trecho do roteiro, já com a fonte decidida e com o resultado do Pexels
    para os que vão de Pexels.

    Só faz o que é grátis: a busca no Pexels. A geração de imagem (que
    custa) fica para gerar_broll_ilustrado(), chamada num passo separado -
    mesma regra do ElevenLabs neste pipeline: nada pago acontece sem você
    mandar.
    """
    plano = parear_narracao_e_visual(roteiro)
    for segmento in plano:
        visual = segmento["visual"]
        segmento["arquivo_real"] = "ARQUIVO REAL" in visual.upper()
        if not USAR_BROLL_IA:
            segmento["fonte"] = "arquivo_real" if segmento["arquivo_real"] else "pexels"
        else:
            segmento["fonte"] = classificar_fonte_do_trecho(segmento["narracao"], visual)
        segmento["arquivo"] = None
        segmento["resultados_pexels"] = []

    if USAR_BROLL_IA:
        plano = _aplicar_teto_de_ilustracoes(plano)

    for segmento in plano:
        if segmento["fonte"] != "pexels":
            continue
        visual = segmento["visual"]
        if not visual:
            segmento["motivo_fonte"] = "trecho sem linha VISUAL no roteiro"
            continue
        termo_en = traduzir_termo_busca(visual)
        print(f"    [{segmento['indice']:02d}] Pexels: '{visual}' -> '{termo_en}'")
        segmento["termo_busca"] = termo_en
        segmento["resultados_pexels"] = buscar_broll_com_alternativas(termo_en, visual)

    ilustrados = sum(1 for s in plano if s["fonte"] == "ia")
    if ilustrados:
        print(
            f"    {ilustrados} trecho(s) marcados para ilustração - nenhuma "
            "imagem foi gerada ainda (é o passo pago/separado)."
        )
    return plano


# -------------------------------------------------------------------------
# Ficha de personagem e descrição de cena
# -------------------------------------------------------------------------

def gerar_ficha_de_personagem(tema, roteiro):
    """
    A "folha de personagem" em texto: a descrição que entra em TODAS as
    imagens do vídeo e faz o mesmo sujeito aparecer em cenas diferentes
    sem imagem de referência.

    Com FICHA_PERSONAGEM_FIXA preenchida, devolve ela direto - o
    personagem é o mesmo em todo vídeo do canal e nem gasta chamada de
    LLM. Vazia, o LLM escolhe a roupa a partir do roteiro.
    """
    if FICHA_PERSONAGEM_FIXA.strip():
        return FICHA_PERSONAGEM_FIXA.strip()

    prompt = (
        "Read the video script below and describe, in ENGLISH, ONE recurring "
        "character to appear in every illustration of this video.\n\n"
        "Answer with a single line of at most 30 words, no commentary. "
        "Describe ONLY stable visual traits that must repeat in every scene: "
        "clothing (colors and garments), build, hair or lack of it, and one "
        "accessory. Do NOT describe facial features (the art style uses a "
        "blank round head with dot eyes). Do NOT name a real person or a "
        "real brand.\n\n"
        "Example of the expected format: bald character in a mustard yellow "
        "t-shirt and blue denim apron, thin black stick arms, pencil behind "
        "the ear\n\n"
        f"TOPIC: {tema}\n\n"
        f"SCRIPT:\n{_truncar(roteiro, 4000, 'roteiro')}"
    )
    try:
        resposta = chamar_llm(prompt, temperature=0.4, max_tokens=300, avisar_corte=False)
    except Exception as erro:
        print(f"    (ficha de personagem: LLM falhou - {type(erro).__name__})")
        return FICHA_PERSONAGEM_PADRAO

    linhas = [l.strip(" -*\"'") for l in (resposta or "").splitlines() if l.strip()]
    ficha = linhas[-1] if linhas else ""
    ficha = re.sub(r"^(character|ficha|answer|resposta)\s*[:\-]\s*", "", ficha, flags=re.I)
    if len(ficha) < 15 or len(ficha) > 400:
        return FICHA_PERSONAGEM_PADRAO
    return ficha


def descrever_cena_para_imagem(narracao, visual):
    """
    Converte o trecho do roteiro numa descrição de cena em inglês, curta e
    concreta - o que a ilustração mostra, não o que a narração diz.
    """
    # O que a frase precisa carregar é justamente o que MUDA de cena pra
    # cena: gesto, expressão, cenário e objetos. A roupa NÃO entra aqui -
    # ela vem da ficha de personagem e tem que ser igual no vídeo inteiro,
    # senão o espectador não reconhece que é o mesmo sujeito.
    prompt = (
        "Turn the script excerpt below into ONE short English sentence "
        "describing what a single illustrated panel should show.\n\n"
        "The sentence MUST contain these three things:\n"
        "1. the character's POSE or GESTURE (what he is doing with his "
        "hands and body: holding a calculator, pointing at a screen, "
        "head in hands, arms crossed);\n"
        "2. his FACIAL EXPRESSION in one word (frustrated, shocked, "
        "tired, focused, satisfied);\n"
        "3. the SETTING and the objects around him (store counter with "
        "invoices, office desk at night with spreadsheets, warehouse "
        "aisle with boxes).\n\n"
        "Rules: at most 30 words; do NOT describe his clothes (they are "
        "fixed for the whole video and come from elsewhere); no camera "
        "directions; no real brand names, logos or real people; do not "
        "mention numbers or statistics; answer with the sentence only, "
        "nothing else.\n\n"
        f"NARRATION: {narracao[:600]}\n"
        f"VISUAL NOTE: {visual[:300]}"
    )
    try:
        resposta = chamar_llm(prompt, temperature=0.5, max_tokens=300, avisar_corte=False)
    except Exception as erro:
        print(f"    (descrição de cena: LLM falhou - {type(erro).__name__})")
        return ""
    linhas = [l.strip(" -*\"'") for l in (resposta or "").splitlines() if l.strip()]
    descricao = linhas[-1] if linhas else ""
    descricao = re.sub(r"^(scene|description|answer)\s*[:\-]\s*", "", descricao, flags=re.I)
    return descricao[:300]


def montar_prompt_de_imagem(descricao_cena, ficha_personagem):
    """Junta cena + personagem + estilo fixo, nessa ordem: o que acontece,
    quem aparece, e como é desenhado."""
    partes = [p for p in (descricao_cena, ficha_personagem, ESTILO_IMAGEM_IA) if p]
    return ". ".join(partes)


# -------------------------------------------------------------------------
# Clientes de geração de imagem
# -------------------------------------------------------------------------

def _gerar_imagem_pollinations(prompt, caminho, semente):
    """
    Pollinations: gratuito e SEM CHAVE de API - por isso é o padrão aqui.
    A imagem vem direto na resposta de um GET.

    Limitação conhecida: não aceita imagem de referência. Neste estilo
    isso pesa pouco (ver comentário no topo da seção), mas é o motivo de
    a ficha de personagem em texto existir.
    """
    from urllib.parse import quote

    url = (
        "https://image.pollinations.ai/prompt/"
        + quote(prompt[:1500])
        + f"?width={IMAGEM_IA_LARGURA}&height={IMAGEM_IA_ALTURA}"
        + f"&seed={semente}&nologo=true&model={POLLINATIONS_MODELO}"
    )
    resposta = requests.get(url, timeout=IMAGEM_IA_TIMEOUT_S)
    resposta.raise_for_status()
    if not resposta.content or len(resposta.content) < 1000:
        raise ValueError("resposta vazia ou pequena demais para ser uma imagem")
    with open(caminho, "wb") as arquivo:
        arquivo.write(resposta.content)
    return caminho


def _gerar_imagem_huggingface(prompt, caminho, semente):
    """
    Hugging Face Inference API: gratuito com token (também grátis), mas
    com fila e limite por hora. Alternativa pra quando o Pollinations
    estiver fora do ar ou devolvendo imagem ruim.
    """
    if not HUGGINGFACE_TOKEN:
        raise ValueError("HUGGINGFACE_TOKEN não configurado no .env")
    resposta = requests.post(
        f"https://api-inference.huggingface.co/models/{HUGGINGFACE_MODELO_IMAGEM}",
        headers={"Authorization": f"Bearer {HUGGINGFACE_TOKEN}"},
        json={"inputs": prompt[:1500], "parameters": {"seed": semente}},
        timeout=IMAGEM_IA_TIMEOUT_S,
    )
    resposta.raise_for_status()
    if resposta.headers.get("content-type", "").startswith("application/json"):
        raise ValueError(f"API devolveu JSON em vez de imagem: {resposta.text[:200]}")
    with open(caminho, "wb") as arquivo:
        arquivo.write(resposta.content)
    return caminho


_PROVEDORES_DE_IMAGEM = {
    "pollinations": _gerar_imagem_pollinations,
    "huggingface": _gerar_imagem_huggingface,
}


def gerar_imagem_ia(prompt, caminho, semente=0):
    """Despacha pro provedor configurado em PROVEDOR_IMAGEM."""
    gerador = _PROVEDORES_DE_IMAGEM.get(PROVEDOR_IMAGEM)
    if not gerador:
        raise ValueError(
            f"PROVEDOR_IMAGEM='{PROVEDOR_IMAGEM}' desconhecido. "
            f"Disponíveis: {', '.join(_PROVEDORES_DE_IMAGEM)}"
        )
    return gerador(prompt, caminho, semente)


def gerar_broll_ilustrado(plano, pasta_destino, tema="", roteiro=""):
    """
    Passo PAGO/lento, separado da montagem do plano: gera uma imagem por
    trecho marcado como "ia".

    Controle de custo e queda para o Pexels:
      - para em MAX_AI_IMAGES_PER_VIDEO, mesmo que sobrem trechos;
      - qualquer falha na geração devolve aquele trecho pro Pexels, em vez
        de deixar o trecho sem imagem;
      - imagem que já existe no disco não é gerada de novo (reaproveita
        quando você repete a etapa).

    Devolve (gerados, rebaixados).
    """
    pendentes = [s for s in plano if s["fonte"] == "ia"]
    if not pendentes:
        return [], []

    pasta_destino.mkdir(parents=True, exist_ok=True)
    ficha = gerar_ficha_de_personagem(tema, roteiro) if roteiro else FICHA_PERSONAGEM_PADRAO
    print(f"    Ficha de personagem: {ficha}")

    gerados = []
    rebaixados = []
    for posicao, segmento in enumerate(pendentes):
        if len(gerados) >= MAX_AI_IMAGES_PER_VIDEO:
            segmento["fonte"] = "pexels"
            segmento["motivo_fonte"] = (
                f"limite de {MAX_AI_IMAGES_PER_VIDEO} imagens do vídeo atingido"
            )
            rebaixados.append(segmento)
            continue

        nome = f"{segmento['indice']:02d}_ia_{_slugificar(segmento['visual'] or segmento['narracao'])}.jpg"
        caminho = pasta_destino / nome
        if caminho.exists():
            print(f"    [{segmento['indice']:02d}] imagem já existe, reaproveitando: {nome}")
            segmento["arquivo"] = nome
            gerados.append(nome)
            continue

        descricao = descrever_cena_para_imagem(segmento["narracao"], segmento["visual"])
        if not descricao:
            descricao = segmento["visual"] or segmento["narracao"][:120]
        prompt = montar_prompt_de_imagem(descricao, ficha)
        segmento["prompt_imagem"] = prompt
        segmento["descricao_cena"] = descricao

        try:
            print(f"    [{segmento['indice']:02d}] gerando ilustração: {descricao[:70]}...")
            gerar_imagem_ia(prompt, caminho, semente=1000 + posicao)
            segmento["arquivo"] = nome
            gerados.append(nome)
        except Exception as erro:
            print(
                f"    [{segmento['indice']:02d}] falhou ({type(erro).__name__}: "
                f"{str(erro)[:120]}) - esse trecho volta pro Pexels."
            )
            segmento["fonte"] = "pexels"
            segmento["motivo_fonte"] = f"geração falhou ({type(erro).__name__})"
            rebaixados.append(segmento)

    # Os rebaixados ainda não têm busca feita (o plano só buscou os que já
    # eram de Pexels) - resolve agora, senão ficam sem imagem nenhuma.
    for segmento in rebaixados:
        visual = segmento["visual"]
        if not visual or segmento.get("resultados_pexels"):
            continue
        termo_en = traduzir_termo_busca(visual)
        segmento["termo_busca"] = termo_en
        segmento["resultados_pexels"] = buscar_broll_com_alternativas(termo_en, visual)

    print(f"    {len(gerados)} ilustração(ões) gerada(s), {len(rebaixados)} trecho(s) devolvido(s) ao Pexels.")
    return gerados, rebaixados


# -------------------------------------------------------------------------
# Manifest
# -------------------------------------------------------------------------

def montar_manifest(plano, tema=""):
    """
    JSON com um item por trecho, na ordem do roteiro, pra importar
    organizado no editor. Sem tempo: a ordem e o texto da narração são o
    que alinha cada imagem no CapCut.
    """
    itens = []
    for segmento in plano:
        itens.append({
            "ordem": segmento["indice"],
            "fonte": segmento["fonte"],
            "arquivo": segmento.get("arquivo"),
            "narracao": segmento["narracao"],
            "visual": segmento["visual"],
            "termo_busca": segmento.get("termo_busca"),
            "prompt_imagem": segmento.get("prompt_imagem"),
            "observacao": segmento.get("motivo_fonte"),
        })
    return {
        "tema": tema,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "total_trechos": len(itens),
        "por_fonte": {
            fonte: sum(1 for i in itens if i["fonte"] == fonte)
            for fonte in sorted({i["fonte"] for i in itens})
        },
        "trechos": itens,
    }


def salvar_manifest(plano, caminho, tema=""):
    manifest = montar_manifest(plano, tema)
    with open(caminho, "w", encoding="utf-8") as arquivo:
        json.dump(manifest, arquivo, ensure_ascii=False, indent=2)
    return caminho


# =========================================================================
# AGENTE 5 - METADADOS (título, thumbnail detalhada, descrição, tags)
# =========================================================================

def gerar_metadados(tema, roteiro):
    # Truncado pelo mesmo motivo do crítico: este prompt embute o roteiro
    # inteiro, e um roteiro anormalmente grande estourava o contexto aqui
    # também (pegado em teste: 59 mil caracteres de prompt).
    prompt = METADADOS_PROMPT.format(
        tema=tema, roteiro=_truncar(roteiro, 20000, "roteiro")
    )
    return chamar_llm(prompt, temperature=0.8, max_tokens=2000)


def extrair_descricao_foto(metadados_texto):
    """Pega o campo 'FOTO DO CRIADOR' de dentro da resposta de metadados.

    O fallback é truncado: devolver o texto inteiro de metadados aqui
    fazia o prompt do agente de imagem chegar a 213 mil caracteres num
    teste - mesmo padrão de bug do fallback das mudanças obrigatórias.
    """
    match = re.search(
        r"FOTO DO CRIADOR.*?:\s*(.+?)(?:\n- [A-ZÀ-Ú]|\Z)",
        metadados_texto,
        re.DOTALL,
    )
    if match:
        return _truncar(match.group(1).strip(), 2000, "descrição da foto")
    return _truncar(metadados_texto, 2000, "metadados (campo não encontrado)")


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

    Tem versão em inglês (mesmas regras, mesmo idioma do roteiro que está
    sendo expandido quando GERAR_EM_INGLES está ligado) - os rótulos
    NARRAÇÃO:/VISUAL: continuam em português dentro do texto em inglês,
    pelo mesmo motivo de sempre: são só marcação fixa pro regex.
    """
    if GERAR_EM_INGLES:
        prompt = (
            f"The script below has about {palavras_atuais} words of "
            f"narration, below the minimum of {alvo_minimo} needed for an "
            "8-10 minute video. Your task is to DEVELOP the script FURTHER -\n\n"
            "RULES THAT CANNOT BE BROKEN (more important than length):\n"
            "- FORBIDDEN to invent any fact, number, person's name, date,\n"
            "  amount, or event that was not in the original script.\n"
            "  'Developing' means rewriting with more words what was\n"
            "  already said - explaining the reasoning better, giving more\n"
            "  context - NEVER adding a new fact that merely sounds\n"
            "  plausible. If unsure whether a number is real, mark\n"
            "  [VERIFICAR], never invent one just to fill space.\n"
            "- FORBIDDEN to continue the story past the ending that already\n"
            "  exists. The original script already has a conclusion - do\n"
            "  not add a 'second act' or new sequence of events after it.\n"
            "  Expand INSIDE the blocks that already exist, never\n"
            "  outside/after them.\n"
            "- FORBIDDEN to duplicate any part of the original script. The\n"
            "  final answer must contain each fact exactly ONCE.\n\n"
            "In this order of priority, within these rules:\n"
            "1. Develop the CORE block further (the decision/conflict part)\n"
            "- add more detail on the management reasoning and the context\n"
            "of each step ALREADY MENTIONED, without bringing in a new fact.\n"
            "2. Make sure every block (backstory, core, conclusion) has at\n"
            "least one mini-hook (new fact, small reveal, question) -\n"
            "insert a new sentence wherever one is missing, but only by\n"
            "rephrasing information that is already in the script.\n"
            "3. Keep the same format: each sentence on a NARRAÇÃO: line,\n"
            "followed on a separate line by VISUAL: (labels stay in\n"
            "Portuguese exactly as shown, content stays in English).\n\n"
            f"TOPIC: {tema}\n\n"
            f"CURRENT SCRIPT:\n{_truncar(roteiro, 20000, 'roteiro')}\n\n"
            "Answer with the FULL revised and expanded SCRIPT (not just "
            "the new part, the entire text start to finish, EXACTLY ONCE), "
            "with no commentary about the task, no repeated step names, no "
            "adding a '---' or any divider in the middle of the text."
        )
    else:
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
            f"ROTEIRO ATUAL:\n{_truncar(roteiro, 20000, 'roteiro')}\n\n"
            "Responda com o ROTEIRO COMPLETO revisado e expandido (não só a "
            "parte nova, o texto inteiro do início ao fim, UMA ÚNICA VEZ), sem "
            "comentário sobre a tarefa, sem repetir nomes de passo, sem "
            "adicionar um '---' ou qualquer divisor no meio do texto."
        )
    return chamar_llm(prompt, temperature=0.7, max_tokens=8192)


def traduzir_roteiro_para_ptbr(roteiro_ingles):
    """
    Último passo do esquema "escrever em inglês": pega o roteiro já
    APROVADO pelo crítico (ainda em inglês) e traduz pra português falado
    natural, preservando rótulos, marcadores e fatos exatamente. Só roda
    quando GERAR_EM_INGLES está ligado - com ele desligado, o roteiro já
    sai em português direto do roteirista, sem precisar desse passo.
    """
    prompt = TRADUCAO_PROMPT.format(
        roteiro_ingles=_truncar(roteiro_ingles, 20000, "roteiro em inglês")
    )
    return chamar_llm(prompt, temperature=0.3, max_tokens=8192)


# =========================================================================
# ORQUESTRAÇÃO - roda os 6 agentes em sequência, com loop de correção
# =========================================================================


# Abaixo deste tamanho o roteiro não é "fraco", é incompleto - e mandar
# um texto incompleto pro crítico desperdiça a tentativa inteira: ele
# reprova por falta de bloco/mini-gancho, o roteirista tenta remendar um
# esqueleto, e o ciclo se repete. Expandir ANTES de avaliar troca uma
# reprovação garantida por uma chamada de expansão.
MINIMO_PALAVRAS_PRA_AVALIAR = 1100


def aplicar_expansao(roteiro, tema, alvo_minimo=MINIMO_PALAVRAS_PRA_AVALIAR):
    """
    Roda o passe de expansão com todas as travas de segurança e devolve o
    roteiro escolhido (expandido ou o original, se a expansão veio ruim).

    Extraído pra função porque agora roda em dois lugares: dentro do loop
    (antes de avaliar, pra não gastar tentativa com roteiro incompleto) e
    depois do loop (rede de segurança final).
    """
    palavras = contar_palavras_narracao(roteiro)
    if palavras >= alvo_minimo:
        return roteiro

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
    poucas_narracoes = roteiro_expandido.count("NARRAÇÃO:") < 3
    if cresceu_alem_do_razoavel or ficou_menor or tem_divisor_solto or poucas_narracoes:
        if cresceu_alem_do_razoavel:
            motivo = f"passou de {nova_contagem} palavras (provável duplicação)"
        elif ficou_menor:
            motivo = (
                f"ficou com MENOS palavras que antes ({nova_contagem} <= {palavras}, "
                "provável corte por limite de token)"
            )
        elif tem_divisor_solto:
            motivo = "tem divisor '---' solto"
        else:
            motivo = "voltou sem as linhas NARRAÇÃO:"
        print(f"  Aviso: expansão descartada - {motivo}. Mantendo a versão de ~{palavras} palavras.")
        return roteiro

    print(f"  Depois da expansão: ~{nova_contagem} palavras.")
    return roteiro_expandido


def _qualidade_da_tentativa(veredito, mudancas, roteiro):
    """
    Nota pra comparar tentativas entre si (menor = melhor). Existe porque
    o loop antigo, ao estourar as tentativas, ficava com a ÚLTIMA versão -
    que não é necessariamente a melhor: uma revisão pode piorar o roteiro
    (encurtar, quebrar formato) e mesmo assim ser a última. Agora o
    pipeline entrega a melhor de todas.

    Ordem de critério: aprovado ganha de reprovado; menos pendência ganha
    de mais pendência; e, empatado, o roteiro mais desenvolvido ganha.
    """
    pendencias = len(_dividir_em_itens(mudancas)) if mudancas else 0
    return (
        0 if veredito == "aprovado" else 1,
        pendencias,
        -contar_palavras_narracao(roteiro),
    )


def gerar_video_completo(tema, max_tentativas=4, pesquisar=None):
    # A pesquisa roda UMA vez, antes da primeira escrita: o material é o
    # mesmo pra todas as tentativas do loop.
    if pesquisar is None:
        pesquisar = USAR_PESQUISA_DE_FATOS
    dossie = None
    if pesquisar:
        # Pesquisa é melhoria, não pré-requisito: qualquer falha aqui
        # (sem internet, fonte fora do ar, resposta estranha) não pode
        # impedir o vídeo de ser gerado.
        try:
            dossie = pesquisar_dossie(tema)
        except Exception as erro:
            print(
                f"  Aviso: a pesquisa de fatos falhou ({type(erro).__name__}: "
                f"{erro}) - seguindo sem dossiê."
            )

    mudancas = None
    roteiro = None
    avaliacao = None
    historico = []  # guarda o motivo de reprovação de CADA tentativa, não só a última
    melhor = None  # melhor tentativa vista até agora (ver _qualidade_da_tentativa)
    pendencias_manuais = ""
    assinatura_anterior = ""
    repeticoes_do_mesmo_pedido = 0

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
            dossie=dossie,
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
            roteiro = escrever_roteiro(
                tema, roteiro_anterior=None, mudancas_obrigatorias=None, dossie=dossie
            )
            if roteiro.count("NARRAÇÃO:") < 3:
                print("    Aviso: segunda tentativa também veio inválida - avaliando mesmo assim.")

        # PRIMEIRA CORREÇÃO MECÂNICA: marca os números antes de qualquer
        # avaliação. Era o campeão de reprovação (88% das avaliações) e
        # nunca foi um problema de julgamento - só de execução repetitiva.
        roteiro, numeros_marcados = marcar_verificar_automatico(roteiro)
        if numeros_marcados:
            print(
                f"    {numeros_marcados} número(s) específico(s) receberam "
                "[VERIFICAR] automaticamente (confira cada um em fonte "
                "primária antes de gravar)."
            )

        # SEGUNDA CORREÇÃO MECÂNICA: roteiro curto demais é expandido
        # ANTES da crítica, não depois. Um esqueleto de 300 palavras seria
        # reprovado nas 4 tentativas por motivos que só o tamanho causa.
        #
        # Com escrita por blocos, o passe de expansão NÃO roda: medido em
        # dois runs reais, ele recuperou 9 palavras num roteiro de 532 e 1
        # palavra num de 361 - não resolve, e cada chamada dessas custa
        # minutos. Quem garante o tamanho agora é a retentativa por bloco,
        # que trabalha sobre 300 palavras em vez de 1.300.
        if not ESCREVER_POR_BLOCOS:
            roteiro = aplicar_expansao(roteiro, tema)
        else:
            palavras_agora = contar_palavras_narracao(roteiro)
            if palavras_agora < MINIMO_PALAVRAS_PRA_AVALIAR:
                print(
                    f"    Aviso: {palavras_agora} palavras "
                    f"(~{estimar_duracao(palavras_agora)}), abaixo do "
                    f"mínimo de {MINIMO_PALAVRAS_PRA_AVALIAR}. O modelo "
                    "local está rendendo pouco por bloco - se repetir, "
                    "aumente os alvos em BLOCOS_DO_ROTEIRO ou ligue "
                    "USAR_NUVEM."
                )
        roteiro, numeros_pos_expansao = marcar_verificar_automatico(roteiro)
        if numeros_pos_expansao:
            print(f"    +{numeros_pos_expansao} número(s) marcados após a expansão.")

        print("  Avaliando roteiro...")
        avaliacao = avaliar_roteiro(roteiro, mudancas_pedidas_antes=mudancas, dossie=dossie)

        # Avaliação fora do template não é reprovação - é resposta perdida.
        # Tenta uma vez mais; se vier torta de novo, ignora a rodada em vez
        # de mandar o texto solto de volta pro roteirista como se fosse
        # uma lista de correções.
        if not avaliacao_segue_template(avaliacao):
            print("    Aviso: o crítico respondeu fora do template - repetindo a avaliação.")
            avaliacao = avaliar_roteiro(roteiro, mudancas_pedidas_antes=mudancas, dossie=dossie)
        if not avaliacao_segue_template(avaliacao):
            print(
                "    Aviso: crítico respondeu fora do template duas vezes - "
                "esta rodada não conta como reprovação (nada foi enviado de "
                "volta pro roteirista)."
            )
            historico.append({
                "tentativa": tentativa,
                "veredito": "avaliação inválida",
                "mudancas_pedidas": "",
                "sugestoes_nao_bloqueantes": [],
            })
            if melhor is None:
                melhor = {
                    "qualidade": _qualidade_da_tentativa("reprovado", "", roteiro),
                    "roteiro": roteiro, "avaliacao": avaliacao,
                    "mudancas": "", "tentativa": tentativa,
                }
            mudancas = None
            continue

        veredito = extrair_veredito(avaliacao)
        mudancas_brutas = extrair_mudancas_obrigatorias(avaliacao)
        registrar_aprendizado(avaliacao)

        # Só bloqueia o roteiro o que o roteirista consegue executar. O
        # resto (sugestão, pedido de pesquisa solto, lista de números sem
        # instrução) é tratado ou descartado aqui - ver
        # filtrar_mudancas_acionaveis.
        mudancas, nao_bloqueantes = filtrar_mudancas_acionaveis(
            mudancas_brutas, roteiro=roteiro
        )
        for descartado in nao_bloqueantes:
            print(f"    (não bloqueia - {descartado['motivo']}): {descartado['item']}")

        if veredito == "reprovado" and mudancas_sao_vazias(mudancas):
            print(
                "    Aviso: crítico reprovou mas não sobrou nenhuma mudança "
                "obrigatória executável (era sugestão ou pedido de pesquisa) "
                "- tratando como APROVADO."
            )
            veredito = "aprovado"

        if veredito == "aprovado" and not mudancas_sao_vazias(mudancas):
            print(
                "    Aviso: crítico escreveu APROVADO mas listou mudança "
                "obrigatória pendente - tratando como REPROVADO."
            )
            veredito = "reprovado"

        print(f"  Veredito: {veredito.upper()}")

        historico.append(
            {
                "tentativa": tentativa,
                "veredito": veredito,
                "mudancas_pedidas": mudancas,
                "sugestoes_nao_bloqueantes": nao_bloqueantes,
            }
        )

        qualidade = _qualidade_da_tentativa(veredito, mudancas, roteiro)
        if melhor is None or qualidade < melhor["qualidade"]:
            melhor = {
                "qualidade": qualidade,
                "roteiro": roteiro,
                "avaliacao": avaliacao,
                "mudancas": mudancas,
                "tentativa": tentativa,
            }

        if veredito == "aprovado":
            break

        print("  Motivo da reprovação (o que será corrigido na próxima tentativa):")
        print(" ", mudancas)

        # TRAVA DE LOOP: se a reprovação é a MESMA de antes, a revisão não
        # está mexendo no ponto reclamado - insistir com o mesmo pedido só
        # gasta tentativa (e cota). Na segunda repetição, para e entrega a
        # melhor versão com a pendência registrada pra revisão manual.
        assinatura = assinatura_do_pedido(mudancas)
        if assinatura and assinatura == assinatura_anterior:
            repeticoes_do_mesmo_pedido += 1
            print(
                f"    Aviso: o crítico repetiu exatamente o mesmo pedido "
                f"({repeticoes_do_mesmo_pedido + 1}ª vez seguida)."
            )
            if repeticoes_do_mesmo_pedido >= 2:
                print(
                    "    Mesmo pedido pela 3ª vez - o loop não está "
                    "convergindo. Parando aqui e entregando a melhor "
                    "versão gerada, com a pendência anotada pra você "
                    "resolver na mão."
                )
                pendencias_manuais = mudancas
                break
        else:
            repeticoes_do_mesmo_pedido = 0
        assinatura_anterior = assinatura
    else:
        print("  Número máximo de tentativas atingido - usando a melhor versão gerada.")
        pendencias_manuais = mudancas

    # Entrega a MELHOR tentativa, não a última - uma revisão pode ter
    # piorado o roteiro e mesmo assim ter sido a última a rodar.
    if melhor and melhor["roteiro"] is not roteiro:
        print(
            f"  Usando o roteiro da tentativa {melhor['tentativa']} "
            "(melhor avaliação do run)."
        )
        roteiro = melhor["roteiro"]
        avaliacao = melhor["avaliacao"]
        # As pendências têm que ser as DESSA versão, não as da última
        # tentativa - senão o relatório manda corrigir um problema que
        # só existia no roteiro que acabou sendo descartado.
        pendencias_manuais = melhor["mudancas"]

    if pendencias_manuais and not mudancas_sao_vazias(pendencias_manuais):
        print("  Pendências que NÃO foram resolvidas (ajuste manualmente se quiser):")
        print(" ", pendencias_manuais)
    else:
        pendencias_manuais = ""

    # Aqui NÃO roda expansão de novo: todo roteiro que chega neste ponto
    # já passou por aplicar_expansao() na sua própria tentativa. Chamar
    # outra vez só repetiria a mesma expansão que já tinha sido
    # descartada - um a dois minutos de GPU por vídeo, sem nada em troca.
    palavras_finais = contar_palavras_narracao(roteiro)
    if palavras_finais < MINIMO_PALAVRAS_PRA_AVALIAR:
        print(
            f"  Aviso: o roteiro final tem ~{palavras_finais} palavras de "
            f"narração (o alvo é 1270-1620). A expansão já foi tentada e não "
            "melhorou - desenvolva mais algum bloco na mão ou gere de novo."
        )

    if GERAR_EM_INGLES:
        print("Traduzindo roteiro (inglês -> português falado natural)...")
        roteiro_traduzido = traduzir_roteiro_para_ptbr(roteiro)
        # Checagem de integridade: a tradução tem que preservar a mesma
        # quantidade de linhas NARRAÇÃO/VISUAL do roteiro em inglês - se
        # vier bem diferente, o casamento narração<->visual quebrou (o
        # resto do pipeline depende de 1 VISUAL por NARRAÇÃO). Nesse caso,
        # melhor manter o roteiro em inglês (com aviso claro) do que
        # seguir com uma estrutura corrompida sem avisar.
        narracoes_antes = roteiro.count("NARRAÇÃO:")
        narracoes_depois = roteiro_traduzido.count("NARRAÇÃO:")
        if abs(narracoes_depois - narracoes_antes) > 1:
            print(
                f"    Aviso: tradução mudou o número de linhas NARRAÇÃO "
                f"({narracoes_antes} -> {narracoes_depois}) - mantendo o "
                "roteiro em inglês por segurança. Revise manualmente ou "
                "rode de novo."
            )
        else:
            roteiro = roteiro_traduzido
            print(f"  Traduzido: {narracoes_depois} linha(s) de narração.")
            # A tradução reescreve as frases e pode perder um marcador no
            # caminho - remarca o que ficou sem, já no texto final.
            roteiro, remarcados = marcar_verificar_automatico(roteiro)
            if remarcados:
                print(f"    {remarcados} número(s) remarcados com [VERIFICAR] após a tradução.")

    # Cruza os números do roteiro final com o material pesquisado - a
    # lista de "não aparece em lugar nenhum" é por onde sua revisão começa.
    conferencias = conferir_numeros_contra_dossie(roteiro, dossie)
    checklist = montar_checklist_verificar(
        conferencias, dossie.get("fontes", []) if dossie else []
    )
    if conferencias:
        sem_respaldo = sum(1 for c in conferencias if not c["confere"])
        print(
            f"  Conferência dos números: {len(conferencias) - sem_respaldo} de "
            f"{len(conferencias)} aparecem no material pesquisado; "
            f"{sem_respaldo} sem respaldo (veja o checklist no .txt)."
        )

    print("Montando o plano de b-roll (Pexels agora; ilustrações no passo separado)...")
    broll = montar_plano_de_broll(roteiro)

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
        "pendencias_manuais": pendencias_manuais,
        "dossie": dossie,
        "checklist_verificar": checklist,
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


def gerar_audio_elevenlabs(texto_narracao_limpo, caminho_saida_mp3, pedir_confirmacao=True):
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

    # A consulta de cota serve pra AVISAR, não pra decidir sozinha onde
    # parar: no log real, 6.419 caracteres custaram 3.094 créditos (menos
    # da metade), ou seja, contar 1 crédito por caractere superestima o
    # custo e deixaria crédito sobrando sem uso. Quem decide o que ainda
    # cabe é a própria API - o loop abaixo tenta todos os blocos e para no
    # primeiro que for recusado por cota, salvando o que já saiu.
    creditos_restantes = None
    cota = consultar_cota_elevenlabs()
    if cota:
        usados, limite = cota
        creditos_restantes = max(limite - usados, 0)
        print(
            f"    Cota ElevenLabs: {creditos_restantes} crédito(s) de "
            f"{limite} ainda disponíveis; esta narração tem {custo_total} "
            "caracteres (o custo real costuma ser menor que isso)."
        )
        if custo_total > creditos_restantes:
            print(
                "    Atenção: a cota pode não cobrir a narração inteira - o "
                "que couber vira áudio e o resto fica num .txt pra você "
                "terminar quando a cota renovar."
            )
    else:
        print(
            "    (não consegui consultar a cota do ElevenLabs - seguindo "
            "e tentando gerar normalmente)"
        )

    # O áudio é a ÚNICA etapa paga do pipeline. Sem esta pergunta, cada
    # execução de teste queima crédito de um roteiro que talvez você nem
    # vá usar - e crédito que acabou só volta quando o ciclo renova.
    if pedir_confirmacao:
        try:
            resposta = input(
                "    Gerar o áudio agora e gastar crédito? "
                "(Enter = sim | n = pular e gerar depois): "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            resposta = ""
        if resposta.startswith("n"):
            caminho_pendente, total = _salvar_narracao_pendente(
                blocos, caminho_saida_mp3
            )
            print(
                f"    Áudio pulado - nenhum crédito gasto. A narração inteira "
                f"({total} caracteres) está em: {caminho_pendente}"
            )
            return None

    dicionario = garantir_dicionario_pronuncia()

    # Quantos caracteres de contexto mandar como previous_text/next_text -
    # não precisa do bloco inteiro, só o suficiente pra dar pista de tom
    JANELA_CONTEXTO = 500

    audio_completo = b""
    gasto = 0
    indice_parada = None  # primeiro bloco que NÃO entrou no áudio

    for i, bloco in enumerate(blocos, 1):
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
                # essa descida sozinho. "style" subiu de 0.3 pra 0.4 na
                # troca pro Flash, tentando compensar um pouco a menor
                # expressividade que a pesquisa aponta nesse modelo -
                # não testado ainda, ouça o resultado. Se ainda soar reto,
                # desça mais stability (até uns 0.3); se ficar instável/
                # errático demais, desça o style de volta.
                "stability": 0.35,
                "similarity_boost": 0.75,
                "style": 0.4,
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
        gasto += len(bloco)  # só pra relatório, não decide mais nada
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


def _texto_do_descarte(descartado):
    """Aceita os dois formatos: o dicionário novo {"item","motivo"} e a
    string simples usada nos JSON salvos antes desta mudança."""
    if isinstance(descartado, dict):
        return descartado.get("item", "")
    return str(descartado)


def _motivo_do_descarte(descartado):
    if isinstance(descartado, dict):
        return descartado.get("motivo", "não bloqueia")
    return "sugestão, não requisito"


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

    if resultado.get("checklist_verificar"):
        partes.append("\n\n" + "=" * 70)
        partes.append("### CHECKLIST DE REVISÃO DOS NÚMEROS ###\n")
        partes.append(resultado["checklist_verificar"])

    if resultado.get("dossie"):
        partes.append("\n\n" + "=" * 70)
        partes.append(
            "### DOSSIÊ DE PESQUISA (o material que o roteirista leu) ###\n"
        )
        partes.append(resultado["dossie"]["texto"])

    partes.append("\n\n" + "=" * 70)
    partes.append("### AVALIAÇÃO DO CRÍTICO (última rodada) ###\n")
    partes.append(resultado["avaliacao"])

    if resultado.get("pendencias_manuais"):
        partes.append("\n\n" + "=" * 70)
        partes.append(
            "### PENDÊNCIAS PRA RESOLVER NA MÃO ###\n"
            "O loop de revisão parou sem resolver os itens abaixo (ou o "
            "crítico repetiu o mesmo pedido sem o roteirista conseguir "
            "atender). O roteiro entregue é a MELHOR versão gerada no run, "
            "não necessariamente a última - ajuste estes pontos no texto "
            "antes de gravar:\n"
        )
        partes.append(resultado["pendencias_manuais"])

    if resultado.get("historico_revisoes"):
        partes.append("\n\n" + "=" * 70)
        partes.append("### HISTÓRICO DE TODAS AS TENTATIVAS (o que foi reprovado) ###\n")
        for item in resultado["historico_revisoes"]:
            partes.append(f"Tentativa {item['tentativa']}: {item['veredito'].upper()}")
            if item["veredito"] == "reprovado":
                partes.append(f"  Motivo: {item['mudancas_pedidas']}")
            for descartado in item.get("sugestoes_nao_bloqueantes", []):
                partes.append(f"  Não reprovou ({_motivo_do_descarte(descartado)}): "
                              f"{_texto_do_descarte(descartado)}")
            partes.append("")

    partes.append("\n\n" + "=" * 70)
    partes.append("### TÍTULO, THUMBNAIL, DESCRIÇÃO E TAGS ###\n")
    partes.append(resultado["metadados"])

    partes.append("\n\n" + "=" * 70)
    partes.append("### PROMPT PRA EDITAR SUA FOTO NO GEMINI ###\n")
    partes.append(resultado["prompt_imagem_gemini"])

    partes.append("\n\n" + "=" * 70)
    partes.append("### B-ROLL POR TRECHO (na ordem do roteiro) ###\n")
    plano = resultado.get("broll") or []
    if isinstance(plano, dict):
        plano = _plano_a_partir_de_dict_antigo(plano)
    for posicao, segmento in enumerate(plano, 1):
        # .get com padrão: o relatório também abre JSON salvo por versões
        # anteriores, onde o segmento não tinha esses campos.
        fonte = segmento.get("fonte", "pexels")
        rotulo = {"ia": "ILUSTRAÇÃO", "pexels": "PEXELS",
                  "arquivo_real": "ARQUIVO REAL"}.get(fonte, fonte)
        indice = segmento.get("indice", posicao)
        partes.append(f"[{indice:02d}] {rotulo}: {segmento.get('visual') or '(sem linha VISUAL)'}")
        if segmento.get("narracao"):
            partes.append(f"     narração: {segmento['narracao'][:110]}")
        if segmento.get("arquivo"):
            partes.append(f"     arquivo: {segmento['arquivo']}")
        if segmento.get("motivo_fonte"):
            partes.append(f"     obs: {segmento['motivo_fonte']}")
        if fonte == "ia" and not segmento.get("arquivo"):
            partes.append("     (ilustração ainda não gerada - é o passo separado)")
        elif fonte == "pexels":
            for item in (segmento.get("resultados_pexels") or [])[:2]:
                partes.append(f"     {item['preview']}")
            if not segmento.get("resultados_pexels"):
                partes.append("     (nenhum resultado encontrado)")
        elif fonte == "arquivo_real":
            partes.append("     (precisa de foto/vídeo real de arquivo, não de banco de stock)")
        partes.append("")

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
        print("Buscando vídeos de maior sucesso dos canais de referência...")
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

        todos_temas = temas_inspirados
        if not todos_temas:
            print(
                "\nNenhum tema automático disponível - digite o seu tema na "
                "pergunta abaixo (ou configure a YOUTUBE_API_KEY no .env pra "
                "voltar a receber sugestões dos canais de referência)."
            )
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
    if USAR_BROLL_IA:
        print("Gerando as ilustrações dos trechos específicos...")
        gerar_broll_ilustrado(
            resultado["broll"], pasta_broll,
            tema=resultado["tema"], roteiro=resultado["roteiro"],
        )
    baixados, pulados = baixar_broll(resultado["broll"], pasta_broll)
    caminho_manifest = salvar_manifest(
        resultado["broll"], pasta_broll / "manifest.json", resultado["tema"]
    )
    print(f"  Manifest do b-roll: {caminho_manifest}")

    print("\nConcluído!")
    print(f"  Texto legível (abra no Bloco de Notas): {caminho_txt}")
    print(f"  Dados completos (JSON):                 {caminho_json}")
    if audio_gerado:
        print(f"  Áudio da narração:                      {audio_gerado}")
    if baixados:
        print(f"  Clipes de b-roll ({len(baixados)}):{' ' * 14}         {pasta_broll}")
    if pulados:
        print(f"  Trechos sem clipe baixado ({len(pulados)}) - veja o .txt pra detalhes")
