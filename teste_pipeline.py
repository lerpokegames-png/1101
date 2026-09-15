# -*- coding: utf-8 -*-
"""
Ensaio do pipeline - roda o fluxo inteiro SEM LLM, SEM internet e SEM
gastar cota nenhuma.

COMO RODAR:
    python teste_pipeline.py

Serve pra responder "eu quebrei alguma coisa?" em 1 segundo, antes de
gastar 20 minutos de GPU num vídeo de verdade. Todo o código do pipeline
roda igual: montagem dos prompts, marcação de [VERIFICAR], passe de
expansão, leitura da resposta do crítico, filtro das mudanças, loop de
revisão, tradução, checklist e relatório .txt.

Só duas coisas são dubladas, porque não existem offline:
  - o LLM (Ollama/Groq) -> respostas roteirizadas
  - a internet (Wikipédia/Wikidata/Google News) -> respostas gravadas no
    formato real dessas APIs

A empresa do ensaio ("NorteSul Logística") é INVENTADA de propósito: o
objetivo é testar a mecânica, não produzir conteúdo sobre empresa real.
"""

import json
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

import feedparser

import pipeline_canal_youtube as pipe

FALHAS = []


def checar(descricao, condicao, detalhe=""):
    if condicao:
        print(f"  [ok] {descricao}")
    else:
        print(f"  [FALHOU] {descricao}" + (f"\n         {detalhe}" if detalhe else ""))
        FALHAS.append(descricao)


# =========================================================================
# 1. MARCAÇÃO AUTOMÁTICA DE [VERIFICAR]
# =========================================================================
def testar_marcacao():
    print("\n1. Marcação automática de [VERIFICAR]")
    linha = "NARRAÇÃO: Em 2015, faturou R$ 2,5 bilhões e cresceu 24% no ano."
    marcado, quantidade = pipe.marcar_verificar_automatico(linha)
    checar("marca todo número específico da narração", quantidade == 3, marcado)
    checar("não parte a palavra em 'US$ 400 milhões'",
           "[VERIFICAR]hões" not in pipe.marcar_verificar_automatico(
               "NARRAÇÃO: Foram US$ 400 milhões no total.")[0])
    checar("números da mesma expressão dividem um marcador",
           pipe.marcar_verificar_automatico(
               "NARRAÇÃO: Entre 2015 e 2019 tudo mudou.")[1] == 1)
    checar("não mexe em linha VISUAL",
           pipe.marcar_verificar_automatico("VISUAL: gráfico com 24% em 2015")[1] == 0)
    checar("rodar de novo não marca nada (idempotente)",
           pipe.marcar_verificar_automatico(marcado)[1] == 0)
    checar("marcador não sobra na narração limpa",
           "[VERIFICAR]" not in pipe.extrair_narracao_limpa(marcado))


# =========================================================================
# 2. FILTRO DAS MUDANÇAS (com as reprovações reais que travavam o loop)
# =========================================================================
def testar_filtro():
    print("\n2. Filtro das mudanças obrigatórias")
    lista_solta = "[2.5 bilhões de reais], [24%], [2015], [2019]"
    acionavel, _ = pipe.filtrar_mudancas_acionaveis(lista_solta)
    checar("lista solta de números vira ordem com verbo",
           acionavel.startswith("- Adicione [VERIFICAR]"), acionavel)

    acionavel, sugestoes = pipe.filtrar_mudancas_acionaveis(
        "- Considerar a possibilidade de adicionar mini-ganchos em cada bloco.")
    checar("sugestão não bloqueia mais o roteiro",
           acionavel == "" and len(sugestoes) == 1, f"{acionavel!r} {sugestoes}")

    acionavel, _ = pipe.filtrar_mudancas_acionaveis(
        "- Verificar a veracidade de todos os eventos apresentados.")
    checar("pedido de pesquisa vira 'adicione [VERIFICAR]'",
           "[VERIFICAR]" in acionavel and "pesquisar" in acionavel.lower(), acionavel)

    checar("mesmo pedido em outra ordem tem a mesma assinatura",
           pipe.assinatura_do_pedido("Adicione X e Y")
           == pipe.assinatura_do_pedido("adicione Y e X."))

    # Casos vindos de um run real: o crítico pediu marcador em número que
    # o código já tinha marcado, e pediu pra nomear a empresa na abertura
    # (o que a regra do canal proíbe). Os dois travavam o loop.
    roteiro_marcado = pipe.marcar_verificar_automatico(
        "NARRAÇÃO: The 2015 financial crisis hit the utility hard.\n"
        "VISUAL: b-roll genérico de escritório\n"
        "NARRAÇÃO: By 2024, only 375 neighborhoods had been connected.\n"
        "VISUAL: b-roll genérico de obra")[0]
    acionavel, descartados = pipe.filtrar_mudancas_acionaveis(
        '- Add [VERIFICAR] next to 2015, 2024, 375 on the NARRAÇÃO lines.\n'
        '- Name the company "Sabesp" in the opening lines.\n'
        '- Remova o jargão "outorga onerosa" ou explique em uma frase.',
        roteiro=roteiro_marcado)
    checar("não repete pedido de [VERIFICAR] já atendido pelo código",
           "2015, 2024, 375" not in acionavel, acionavel)
    checar("recusa pedido de nomear a empresa na abertura",
           "Sabesp" not in acionavel, acionavel)
    checar("mantém o pedido legítimo da mesma lista",
           "outorga onerosa" in acionavel, acionavel)
    checar("registra o motivo de cada descarte",
           len(descartados) == 2 and all(d.get("motivo") for d in descartados),
           str(descartados))

    sem_marcador = "NARRAÇÃO: Foram 900 ligações no bairro.\nVISUAL: b-roll"
    acionavel, _ = pipe.filtrar_mudancas_acionaveis(
        "- Add [VERIFICAR] next to 900.", roteiro=sem_marcador)
    checar("número de fato sem marcador continua reprovando", "900" in acionavel)
    acionavel, _ = pipe.filtrar_mudancas_acionaveis(
        "- Nomeie a empresa real no miolo do roteiro.", roteiro=roteiro_marcado)
    checar("nomear a empresa no MIOLO continua sendo pedido válido",
           "miolo" in acionavel, acionavel)


# =========================================================================
# 3. LEITURA DA RESPOSTA DO CRÍTICO
# =========================================================================
def testar_leitura_do_critico():
    print("\n3. Leitura da resposta do crítico")
    checar("lê VEREDITO com markdown em volta",
           pipe.extrair_veredito("**VEREDITO:** REPROVADO") == "reprovado")
    checar("lê rótulo sem acento",
           pipe.extrair_veredito("MUDANCAS OBRIGATORIAS: Nenhuma\nVEREDITO: APROVADO") == "aprovado")
    checar("não invade o campo seguinte",
           pipe.extrair_mudancas_obrigatorias(
               "MUDANÇAS OBRIGATÓRIAS: Troque o fecho.\nNÚMEROS SEM VERIFICAR: 24%\nVEREDITO: REPROVADO"
           ) == "Troque o fecho.")
    roteiro_no_lugar_da_avaliacao = "NARRAÇÃO: frase\nVISUAL: b-roll genérico\n" * 20
    checar("reconhece avaliação fora do template",
           not pipe.avaliacao_segue_template(roteiro_no_lugar_da_avaliacao))


# =========================================================================
# 4. ESCOLHA DO ARTIGO CERTO NA WIKIPÉDIA
# =========================================================================
def testar_escolha_do_artigo():
    print("\n4. Escolha do artigo certo na Wikipédia")
    for titulo, intro, desambig, esperado in [
        ("NorteSul (desambiguação)", "NorteSul pode referir-se a:", True, None),
        ("Lista de transportadoras", "Esta é uma lista.", False, None),
        ("NorteSul (rio)", "Curso d'água de 40 quilômetros.", False, 0),
    ]:
        nota = pipe._pontuar_candidato(titulo, "NorteSul Logística", intro, desambig)
        checar(f"descarta/rebaixa '{titulo}'", nota == esperado, f"nota={nota}")
    nota_empresa = pipe._pontuar_candidato(
        "NorteSul Logística", "NorteSul Logística",
        "NorteSul Logística é uma empresa transportadora fundada em 2004, sediada em MG.",
        False)
    checar("artigo da empresa ganha de todos", (nota_empresa or 0) > 10, f"nota={nota_empresa}")


# =========================================================================
# 7. ESCRITA POR BLOCOS (o que faz um 7B entregar 1.400 palavras)
# =========================================================================
def _llm_que_entrega(fator):
    """Dublê do modelo local: entrega uma fração do tamanho pedido. Um 7B
    real rende perto de 85% do alvo por bloco; abaixo disso é modelo em
    dificuldade."""
    def responder(prompt, **kwargs):
        alvo = re.search(r"perto de (\d+)", prompt)
        palavras = int(int(alvo.group(1)) * fator) if alvo else 20
        linhas, restante = [], palavras
        while restante > 0:
            n = min(18, restante)
            restante -= n
            linhas.append("NARRAÇÃO: " + " ".join(["palavra"] * n))
            linhas.append("VISUAL: b-roll genérico de escritório")
        return "\n".join(linhas)
    return responder


def testar_escrita_por_blocos():
    print("\n7. Escrita por blocos")
    original = {"llm": pipe.chamar_llm, "ingles": pipe.GERAR_EM_INGLES}
    pipe.GERAR_EM_INGLES = False
    try:
        pipe.chamar_llm = _llm_que_entrega(0.85)
        roteiro = pipe.escrever_roteiro_por_blocos("tema de teste")
        total = pipe.contar_palavras_narracao(roteiro)
        checar("roteiro fecha dentro do alvo do canal (1270-1620)",
               1270 <= total <= 1620, f"{total} palavras")
        checar("formato NARRAÇÃO/VISUAL preservado em todos os blocos",
               roteiro.count("NARRAÇÃO:") == roteiro.count("VISUAL:")
               and roteiro.count("NARRAÇÃO:") > 20)
        checar("duração estimada bate com a contagem",
               pipe.estimar_duracao(1500).startswith("10min"),
               pipe.estimar_duracao(1500))

        # O alvo tem que ser pedido como TOPO da faixa: pedindo "entre X e
        # Y" o modelo ancora no piso e seis blocos fecham abaixo do mínimo.
        prompt = pipe._prompt_do_bloco(
            pipe.BLOCOS_DO_ROTEIRO[1], "tema", "", "")
        checar("o prompt do bloco pede o topo da faixa, não a faixa",
               "perto de 350" in prompt and "Abaixo de 280" in prompt,
               prompt[-200:])

        chamadas = {"n": 0}
        base = _llm_que_entrega(0.5)
        def contar(prompt, **kwargs):
            chamadas["n"] += 1
            return base(prompt, **kwargs)
        pipe.chamar_llm = contar
        pipe.escrever_roteiro_por_blocos("tema")
        checar("bloco abaixo do mínimo é refeito uma vez",
               chamadas["n"] == 2 * len(pipe.BLOCOS_DO_ROTEIRO),
               f"{chamadas['n']} chamadas")
    finally:
        pipe.chamar_llm = original["llm"]
        pipe.GERAR_EM_INGLES = original["ingles"]


# =========================================================================
# 8. FLUXO COMPLETO (pesquisa -> roteiro -> crítico -> tradução -> relatório)
# =========================================================================
ARTIGO_FALSO = """NorteSul Logística é uma transportadora fictícia fundada em 2004.


== História ==

A empresa começou com 12 caminhões e um galpão alugado.
Em 2011 recebeu o primeiro aporte, de R$ 45 milhões, e passou a operar em nove estados.
Em 2016 uma falha no sistema de roteirização atrasou 30% das entregas do trimestre.


== Ligações externas ==

Site oficial. Categoria: empresas fictícias.
"""

# A busca devolve 4 candidatos de propósito: uma desambiguação, uma lista,
# a empresa e um homônimo. Só a empresa pode ser escolhida.
RESPOSTAS_HTTP = {
    ("query", "search"): {"query": {"search": [
        {"title": "NorteSul (desambiguação)"},
        {"title": "Lista de transportadoras do Brasil"},
        {"title": "NorteSul Logística"},
        {"title": "NorteSul (rio)"},
    ]}},
    ("query", "previa"): {"query": {"pages": {
        "1": {"title": "NorteSul (desambiguação)",
              "extract": "NorteSul pode referir-se a:",
              "pageprops": {"disambiguation": ""}},
        "2": {"title": "Lista de transportadoras do Brasil",
              "extract": "Esta é uma lista de transportadoras.", "pageprops": {}},
        "3": {"title": "NorteSul Logística",
              "extract": ("NorteSul Logística é uma empresa transportadora "
                          "fictícia fundada em 2004, sediada em Minas Gerais, "
                          "com operação em nove estados do país."),
              "pageprops": {"wikibase_item": "Q999999"}},
        "4": {"title": "NorteSul (rio)",
              "extract": "Curso d'água de 40 quilômetros.",
              "pageprops": {"wikibase_item": "Q555"}},
    }}},
    ("query", "extracts"): {"query": {"pages": {"1": {
        "title": "NorteSul Logística", "extract": ARTIGO_FALSO}}}},
    ("wbsearchentities", None): {"search": [{"id": "Q999999"}]},
    ("wbgetentities", "claims"): {"entities": {"Q999999": {"claims": {
        "P571": [{"mainsnak": {"datavalue": {
            "type": "time", "value": {"time": "+2004-03-01T00:00:00Z"}}}}],
        "P1128": [{"mainsnak": {"datavalue": {
            "type": "quantity", "value": {"amount": "+4200"}}},
            "qualifiers": {"P585": [{"datavalue": {
                "type": "time", "value": {"time": "+2022-01-01T00:00:00Z"}}}]}}],
    }}}},
    ("wbgetentities", "labels"): {"entities": {}},
}

RSS_FALSO = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>NorteSul troca sistema de roteirização após falha</title>
<pubDate>Wed, 05 Oct 2016 12:00:00 GMT</pubDate>
<source url="http://exemplo">Diário do Transporte</source></item>
</channel></rss>"""

ROTEIRO_FALSO = "\n".join([
    "NARRAÇÃO: Um bug de software congelou 30% das entregas de um trimestre inteiro.",
    "VISUAL: b-roll genérico de esteira de encomendas parada",
    "NARRAÇÃO: Em 2004 a empresa começou com 12 caminhões e um galpão alugado.",
    "VISUAL: b-roll genérico de caminhão saindo de galpão",
    "NARRAÇÃO: Em 2011 já tinha levantado R$ 45 milhões e chegado a nove estados.",
    "VISUAL: b-roll genérico de mapa em tela",
    "NARRAÇÃO: A diretoria tinha cortado 18% do orçamento de roteirização naquele ano.",
    "VISUAL: b-roll genérico de reunião de diretoria",
] + [
    f"NARRAÇÃO: Linha {i} desenvolve o raciocínio de gestão por trás da decisão, "
    "em linguagem falada, com detalhe suficiente pra sustentar a história.\n"
    "VISUAL: b-roll genérico de escritório"
    for i in range(45)
])


def _avaliacao(mudancas, veredito, evento="Nenhum encontrado"):
    return (
        "NOTA DO GANCHO (0 a 10): 8\nMOTIVO: bom gancho\n"
        "PONTOS DE QUEDA: Nenhum encontrado\n"
        "MINI-GANCHOS FALTANDO: Todos os blocos têm mini-gancho\n"
        "JARGÃO NÃO EXPLICADO: Nenhum encontrado\nFECHO: específico\n"
        "VISUAIS PROBLEMÁTICOS: Nenhum encontrado\n"
        "RÓTULO DE INSTRUÇÃO VAZADO: Nenhum encontrado\n"
        "NÚMEROS SEM VERIFICAR: Nenhum encontrado\n"
        "PESSOA INVENTADA: Nenhuma encontrada\n"
        f"EVENTO SEM VERIFICAR: {evento}\n"
        "EMPRESA IDENTIFICÁVEL MAS NÃO NOMEADA: Nenhum encontrado\n"
        "CHANCE DE RETENÇÃO: alta\n"
        f"MUDANÇAS OBRIGATÓRIAS: {mudancas}\n"
        f"VEREDITO: {veredito}\n"
    )


def testar_broll_hibrido():
    print("\n6. B-roll híbrido (Pexels + ilustração)")
    roteiro = (
        "NARRAÇÃO: Um panorama do setor inteiro naquele ano difícil.\n"
        "VISUAL: b-roll genérico de cidade ao amanhecer\n"
        "NARRAÇÃO: Outro momento da história, com a mesma imagem de apoio.\n"
        "VISUAL: b-roll genérico de cidade ao amanhecer\n"
        "NARRAÇÃO: O dono confere a planilha de despesas sozinho de madrugada.\n"
        "VISUAL: [ARQUIVO REAL] o dono olhando as contas no balcão\n"
        "NARRAÇÃO: E o faturamento despencou no trimestre seguinte.\n"
        "VISUAL: b-roll genérico de gráfico caindo na tela"
    )
    segmentos = pipe.parear_narracao_e_visual(roteiro)
    checar("um segmento por trecho, mesmo com VISUAL repetido",
           len(segmentos) == 4, f"{len(segmentos)} segmentos")
    checar("cada segmento leva a própria narração",
           all(s["narracao"] for s in segmentos))
    checar("cena genérica vai pro Pexels",
           pipe.classificar_fonte_do_trecho(segmentos[0]["narracao"],
                                            segmentos[0]["visual"]) == "pexels")
    checar("[ARQUIVO REAL] vira ilustração",
           pipe.classificar_fonte_do_trecho(segmentos[2]["narracao"],
                                            segmentos[2]["visual"]) == "ia")

    original = {"traduz": pipe.traduzir_termo_busca,
                "busca": pipe.buscar_broll_com_alternativas,
                "llm": pipe.chamar_llm, "requests": pipe.requests}
    pasta = Path(tempfile.mkdtemp(prefix="broll_teste_"))
    try:
        pipe.traduzir_termo_busca = lambda t: "generic city sunrise"
        pipe.buscar_broll_com_alternativas = lambda en, pt: [
            {"id": 1, "preview": "http://exemplo/v.mp4", "duracao_s": 10}]
        pipe.chamar_llm = lambda prompt, **k: (
            "bald character in a mustard yellow t-shirt and blue denim apron"
            if "recurring character" in prompt
            else "a shop owner alone at night checking expense sheets")
        plano = pipe.montar_plano_de_broll(roteiro)
        checar("trecho de ilustração não gasta busca no Pexels",
               plano[2]["resultados_pexels"] == [])

        pipe.requests = types.SimpleNamespace(get=lambda url, timeout=None, **kw:
            types.SimpleNamespace(content=b"\xff\xd8\xff" + b"0" * 2000,
                                  raise_for_status=lambda: None,
                                  headers={"content-type": "image/jpeg"}))
        gerados, _ = pipe.gerar_broll_ilustrado(plano, pasta, tema="t", roteiro=roteiro)
        checar("gera a ilustração do trecho específico", len(gerados) == 1, str(gerados))
        prompt_final = plano[2].get("prompt_imagem", "")
        ficha_usada = pipe.gerar_ficha_de_personagem("t", roteiro)
        checar("prompt junta cena + ficha de personagem + estilo fixo",
               all(marca in prompt_final for marca in
                   ("shop owner", ficha_usada, pipe.ESTILO_IMAGEM_IA)),
               prompt_final[:160])

        # provedor fora do ar: o trecho não pode ficar sem imagem
        plano2 = pipe.montar_plano_de_broll(roteiro)
        def quebrado(url, timeout=None, **kw):
            raise ConnectionError("provedor fora do ar")
        pipe.requests = types.SimpleNamespace(get=quebrado)
        gerados2, rebaixados = pipe.gerar_broll_ilustrado(
            plano2, Path(tempfile.mkdtemp()), tema="t", roteiro=roteiro)
        checar("falha na geração devolve o trecho pro Pexels",
               gerados2 == [] and plano2[2]["fonte"] == "pexels"
               and plano2[2]["resultados_pexels"] != [],
               str(plano2[2]))

        # O personagem tem que ser o MESMO em todas as cenas do vídeo -
        # sem rosto pra reconhecer, a roupa é a única âncora que sobra.
        fichas = {pipe.gerar_ficha_de_personagem("t", roteiro) for _ in range(3)}
        checar("ficha de personagem é estável dentro do vídeo", len(fichas) == 1, str(fichas))
        checar("ficha fixa, quando definida, vale pra todo vídeo",
               pipe.FICHA_PERSONAGEM_FIXA.strip() == "" or
               pipe.gerar_ficha_de_personagem("outro tema", "outro roteiro")
               == pipe.FICHA_PERSONAGEM_FIXA.strip())

        # Com a ficha automática (o padrão), o personagem se veste conforme
        # a história - mas se o LLM cair, a imagem não pode sair sem
        # personagem nenhum.
        def llm_fora(*a, **k):
            raise ConnectionError("llm fora do ar")
        pipe.chamar_llm = llm_fora
        ficha_de_emergencia = pipe.gerar_ficha_de_personagem("t", roteiro)
        checar("LLM fora do ar ainda entrega uma ficha utilizável",
               len(ficha_de_emergencia) > 20 and "head" in ficha_de_emergencia,
               repr(ficha_de_emergencia))

        manifest = pipe.montar_manifest(plano, tema="t")
        checar("manifest tem um item por trecho, na ordem",
               [t["ordem"] for t in manifest["trechos"]] == [1, 2, 3, 4])
        checar("manifest separa as fontes",
               manifest["por_fonte"] == {"ia": 1, "pexels": 3},
               str(manifest["por_fonte"]))
    finally:
        pipe.traduzir_termo_busca = original["traduz"]
        pipe.buscar_broll_com_alternativas = original["busca"]
        pipe.chamar_llm = original["llm"]
        pipe.requests = original["requests"]
        shutil.rmtree(pasta, ignore_errors=True)


def testar_fluxo_completo():
    print("\n8. Fluxo completo do vídeo")
    pasta = Path(tempfile.mkdtemp(prefix="ensaio_pipeline_"))
    original = {
        "requests": pipe.requests,
        "chamar_llm": pipe.chamar_llm,
        "plano": pipe.montar_plano_de_broll,
        "cache": pipe.PASTA_CACHE_PESQUISA,
        "parse": feedparser.parse,
        "ingles": pipe.GERAR_EM_INGLES,
        "estatisticas": pipe.registrar_aprendizado,
    }
    pipe.PASTA_CACHE_PESQUISA = pasta / ".cache_pesquisa"
    pipe.GERAR_EM_INGLES = False  # o ensaio escreve direto em português
    pipe.registrar_aprendizado = lambda texto: {}  # não suja suas estatísticas

    class RespostaFalsa:
        def __init__(self, dados):
            self.dados = dados

        def raise_for_status(self):
            pass

        def json(self):
            return self.dados

    def get_falso(url, params=None, headers=None, timeout=None):
        acao = params.get("action")
        if acao == "query":
            if params.get("list") == "search":
                chave = ("query", "search")
            elif "pageprops" in params.get("prop", ""):
                chave = ("query", "previa")
            else:
                chave = ("query", "extracts")
        elif acao == "wbgetentities":
            chave = ("wbgetentities",
                     "claims" if "claims" in params.get("props", "") else "labels")
        else:
            # Tendo o wikibase_item do artigo, o Wikidata NÃO pode mais ser
            # procurado por nome - é aí que ele cai noutra entidade.
            if acao == "wbsearchentities":
                FALHAS.append("buscou no Wikidata por nome tendo o qid do artigo")
            chave = (acao, None)
        return RespostaFalsa(RESPOSTAS_HTTP[chave])

    pipe.requests = types.SimpleNamespace(get=get_falso)
    feedparser.parse = (lambda real: lambda url: real(RSS_FALSO))(feedparser.parse)
    def plano_falso(roteiro):
        segmentos = pipe.parear_narracao_e_visual(roteiro)
        for segmento in segmentos:
            segmento.update(fonte="pexels", arquivo=None, arquivo_real=False,
                            resultados_pexels=[])
        return segmentos
    pipe.montar_plano_de_broll = plano_falso

    rodadas = {"critico": 0}

    def llm_dublê(prompt, temperature=0.7, max_tokens=8192, avisar_corte=True):
        if "EMPRESA:" in prompt and "TERMOS:" in prompt:
            return "EMPRESA: NorteSul Logística\nTERMOS: NorteSul Logística"
        if "editor crítico de retenção" in prompt or "audience-retention critic" in prompt:
            rodadas["critico"] += 1
            if rodadas["critico"] == 1:
                # O pedido tem que ser algo que o CÓDIGO não resolve
                # sozinho - se fosse "adicione [VERIFICAR] em 18%", o
                # filtro descartaria (já está marcado) e o roteiro seria
                # aprovado de primeira, sem exercitar o loop.
                return _avaliacao(
                    '\n- Remova o jargão "roteirização dinâmica" ou explique'
                    " em uma frase simples."
                    "\n- Considerar a possibilidade de reforçar o fecho.",
                    "REPROVADO",
                    evento="O corte de 18% não aparece no dossiê",
                )
            return _avaliacao("Nenhuma", "APROVADO")
        if "metadados de YouTube" in prompt:
            return ("TÍTULOS:\n1. O bug que parou 30% das entregas\n"
                    "FOTO: pessoa com expressão de espanto diante de um galpão parado\n"
                    "DESCRIÇÃO: como um corte de custos virou crise logística\nTAGS: logística")
        if "Gemini" in prompt:
            return "Edite a foto: mesma pessoa, expressão de espanto, galpão ao fundo."
        return ROTEIRO_FALSO

    pipe.chamar_llm = llm_dublê

    try:
        resultado = pipe.gerar_video_completo(
            "o bug que travou as entregas de uma transportadora"
        )
        vereditos = [i["veredito"] for i in resultado["historico_revisoes"]]
        checar("loop reprova, corrige e aprova", vereditos == ["reprovado", "aprovado"], str(vereditos))
        checar("sugestão foi separada da reprovação",
               resultado["historico_revisoes"][0]["sugestoes_nao_bloqueantes"] != [])
        checar("dossiê foi montado com as três fontes",
               all(marca in resultado["dossie"]["texto"]
                   for marca in ("WIKIPÉDIA", "FATOS ESTRUTURADOS", "MANCHETES")))
        checar("seção irrelevante ficou fora do dossiê",
               "Ligações externas" not in resultado["dossie"]["texto"])
        checar("escolheu o artigo da empresa, não a desambiguação nem a lista",
               "WIKIPÉDIA - NorteSul Logística" in resultado["dossie"]["texto"],
               resultado["dossie"]["texto"][:200])
        checar("usou o ID do Wikidata que veio do próprio artigo",
               "Q999999" in " ".join(resultado["dossie"]["fontes"]),
               str(resultado["dossie"]["fontes"]))
        conferencias = pipe.conferir_numeros_contra_dossie(
            resultado["roteiro"], resultado["dossie"])
        por_trecho = {c["trecho"]: c["confere"] for c in conferencias}
        checar("checklist confirma número que está no dossiê",
               por_trecho.get("R$ 45 milhões") is True, str(por_trecho))
        checar("checklist aponta número sem respaldo",
               por_trecho.get("18%") is False, str(por_trecho))
        checar("narração limpa sai sem rótulo e sem marcador",
               "[VERIFICAR]" not in resultado["narracao_limpa"]
               and "NARRAÇÃO" not in resultado["narracao_limpa"])

        relatorio = pipe.montar_relatorio_txt(resultado)
        for secao in ("### CHECKLIST DE REVISÃO DOS NÚMEROS ###",
                      "### DOSSIÊ DE PESQUISA",
                      "### HISTÓRICO DE TODAS AS TENTATIVAS"):
            checar(f"relatório tem a seção {secao.strip('# ')}", secao in relatorio)

        arquivo = pasta / "video_ENSAIO.txt"
        arquivo.write_text(relatorio, encoding="utf-8")
        (pasta / "video_ENSAIO.json").write_text(
            json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  Saída completa do ensaio em: {pasta}")
    finally:
        pipe.requests = original["requests"]
        pipe.chamar_llm = original["chamar_llm"]
        pipe.montar_plano_de_broll = original["plano"]
        pipe.PASTA_CACHE_PESQUISA = original["cache"]
        feedparser.parse = original["parse"]
        pipe.GERAR_EM_INGLES = original["ingles"]
        pipe.registrar_aprendizado = original["estatisticas"]
        shutil.rmtree(pasta / ".cache_pesquisa", ignore_errors=True)


if __name__ == "__main__":
    print("=" * 70)
    print("ENSAIO DO PIPELINE - sem LLM, sem internet, sem gastar cota")
    print("=" * 70)
    testar_marcacao()
    testar_filtro()
    testar_leitura_do_critico()
    testar_escolha_do_artigo()
    testar_broll_hibrido()
    testar_escrita_por_blocos()
    testar_fluxo_completo()
    print("\n" + "=" * 70)
    if FALHAS:
        print(f"{len(FALHAS)} VERIFICAÇÃO(ÕES) FALHOU/FALHARAM:")
        for f in FALHAS:
            print(f"  - {f}")
        sys.exit(1)
    print("TUDO PASSOU - o pipeline está inteiro.")
