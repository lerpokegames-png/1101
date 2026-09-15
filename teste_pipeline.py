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
# 4. FLUXO COMPLETO (pesquisa -> roteiro -> crítico -> tradução -> relatório)
# =========================================================================
ARTIGO_FALSO = """NorteSul Logística é uma transportadora fictícia fundada em 2004.


== História ==

A empresa começou com 12 caminhões e um galpão alugado.
Em 2011 recebeu o primeiro aporte, de R$ 45 milhões, e passou a operar em nove estados.
Em 2016 uma falha no sistema de roteirização atrasou 30% das entregas do trimestre.


== Ligações externas ==

Site oficial. Categoria: empresas fictícias.
"""

RESPOSTAS_HTTP = {
    ("query", "search"): {"query": {"search": [{"title": "NorteSul Logística"}]}},
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


def testar_fluxo_completo():
    print("\n4. Fluxo completo do vídeo")
    pasta = Path(tempfile.mkdtemp(prefix="ensaio_pipeline_"))
    original = {
        "requests": pipe.requests,
        "chamar_llm": pipe.chamar_llm,
        "broll": pipe.montar_lista_broll,
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
            chave = ("query", "search" if params.get("list") == "search" else "extracts")
        elif acao == "wbgetentities":
            chave = ("wbgetentities",
                     "claims" if "claims" in params.get("props", "") else "labels")
        else:
            chave = (acao, None)
        return RespostaFalsa(RESPOSTAS_HTTP[chave])

    pipe.requests = types.SimpleNamespace(get=get_falso)
    feedparser.parse = (lambda real: lambda url: real(RSS_FALSO))(feedparser.parse)
    pipe.montar_lista_broll = lambda roteiro: {"esteira de encomendas parada": []}

    rodadas = {"critico": 0}

    def llm_dublê(prompt, temperature=0.7, max_tokens=8192, avisar_corte=True):
        if "EMPRESA:" in prompt and "TERMOS:" in prompt:
            return "EMPRESA: NorteSul Logística\nTERMOS: NorteSul Logística"
        if "editor crítico de retenção" in prompt or "audience-retention critic" in prompt:
            rodadas["critico"] += 1
            if rodadas["critico"] == 1:
                return _avaliacao(
                    "\n- Adicione [VERIFICAR] no corte de 18% do orçamento."
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
        pipe.montar_lista_broll = original["broll"]
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
    testar_fluxo_completo()
    print("\n" + "=" * 70)
    if FALHAS:
        print(f"{len(FALHAS)} VERIFICAÇÃO(ÕES) FALHOU/FALHARAM:")
        for f in FALHAS:
            print(f"  - {f}")
        sys.exit(1)
    print("TUDO PASSOU - o pipeline está inteiro.")
