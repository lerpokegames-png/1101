"""
Interface web (bonita, sem terminal) pro pipeline de criação de vídeos.

COMO RODAR:
    1. pip install streamlit
    2. Deixe este arquivo na MESMA pasta do pipeline_canal_youtube.py e
       do seu .env
    3. No terminal: streamlit run app_web.py
       (isso abre uma aba no seu navegador automaticamente - fica rodando
       localmente na sua máquina, nada é enviado pra fora além das
       chamadas de API que o próprio pipeline já faz)

Este arquivo não duplica a lógica do pipeline - ele importa as funções de
pipeline_canal_youtube.py e só desenha a interface em volta delas. Se você
mudar uma regra de prompt ou corrigir um bug no pipeline, funciona igual
aqui, sem precisar mexer neste arquivo.
"""

import json
from datetime import datetime

import streamlit as st

import pipeline_canal_youtube as pipe

st.set_page_config(
    page_title="Fábrica de Vídeos - Empresas & Administração",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 Fábrica de Vídeos")
st.caption(
    "Roteiro, b-roll, título/thumbnail e narração - tudo automatizado, "
    "sem terminal."
)

PASTA_SAIDAS = pipe.PASTA_DO_SCRIPT / "saidas"
PASTA_SAIDAS.mkdir(exist_ok=True)

if "temas" not in st.session_state:
    st.session_state.temas = []
if "resultado_atual" not in st.session_state:
    st.session_state.resultado_atual = None
if "carimbo_atual" not in st.session_state:
    st.session_state.carimbo_atual = None


def salvar_json_e_txt(resultado, carimbo):
    caminho_json = PASTA_SAIDAS / f"video_{carimbo}.json"
    caminho_txt = PASTA_SAIDAS / f"video_{carimbo}.txt"
    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    with open(caminho_txt, "w", encoding="utf-8") as f:
        f.write(pipe.montar_relatorio_txt(resultado))
    return caminho_json, caminho_txt


aba_novo, aba_salvos, aba_aprendizado = st.tabs(
    ["🆕 Gerar novo vídeo", "📁 Vídeos salvos", "📊 Aprendizado"]
)

# =========================================================================
# ABA 1 - GERAR NOVO VÍDEO
# =========================================================================
with aba_novo:
    if not st.session_state.resultado_atual:
        st.subheader("1. Escolha o tema")

        col_busca, col_manual = st.columns(2)

        with col_busca:
            if st.button("🔍 Buscar temas nos canais de referência"):
                if not pipe.YOUTUBE_KEY:
                    st.warning(
                        "YOUTUBE_API_KEY não configurada no .env - "
                        "configure pra usar esta busca."
                    )
                else:
                    with st.spinner("Buscando vídeos de maior sucesso..."):
                        titulos_referencia = pipe.buscar_referencias()
                        if titulos_referencia:
                            _, temas = pipe.gerar_temas_por_referencia(
                                titulos_referencia
                            )
                            st.session_state.temas = temas
                        else:
                            st.warning("Nenhum resultado encontrado.")

        tema_escolhido = None
        if st.session_state.temas:
            tema_escolhido = st.radio(
                "Temas encontrados:", st.session_state.temas, index=None
            )

        with col_manual:
            tema_manual = st.text_input("Ou digite o seu próprio tema:")

        if tema_manual:
            tema_escolhido = tema_manual

        st.divider()
        pesquisar = st.checkbox(
            "🔎 Pesquisar fatos sobre o tema antes de escrever (recomendado)",
            value=pipe.USAR_PESQUISA_DE_FATOS,
            help=(
                "Levanta material real sobre o tema (Wikipédia, Wikidata e "
                "manchetes com data) e entrega pro roteirista antes dele "
                "escrever, pra ele contar uma história que existe em vez de "
                "uma história plausível. Não usa chave de API, leva alguns "
                "segundos e fica em cache. Desligue só se estiver sem "
                "internet."
            ),
        )
        gerar = st.button(
            "🚀 Gerar roteiro completo",
            type="primary",
            disabled=not tema_escolhido,
        )

        if gerar and tema_escolhido:
            log_container = st.empty()
            linhas_log = []

            def registrar_log(msg):
                linhas_log.append(msg)
                log_container.code("\n".join(linhas_log[-15:]))

            with st.spinner(f"Gerando vídeo sobre: {tema_escolhido}"):
                # Redireciona os prints do pipeline pra um log visível na
                # tela, em vez de sumirem no terminal que você não está
                # olhando enquanto usa o navegador.
                import builtins

                print_original = builtins.print

                def print_capturado(*args, **kwargs):
                    registrar_log(" ".join(str(a) for a in args))

                builtins.print = print_capturado
                try:
                    resultado = pipe.gerar_video_completo(
                        tema_escolhido, pesquisar=pesquisar
                    )
                finally:
                    builtins.print = print_original

            carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
            salvar_json_e_txt(resultado, carimbo)
            st.session_state.resultado_atual = resultado
            st.session_state.carimbo_atual = carimbo
            st.success("Roteiro pronto! Revise abaixo antes de gastar crédito no áudio.")
            st.rerun()

    else:
        resultado = st.session_state.resultado_atual
        carimbo = st.session_state.carimbo_atual

        st.subheader(f"📌 {resultado['tema']}")

        col_voltar, col_refazer = st.columns(2)

        with col_voltar:
            if st.button("⬅️ Começar um vídeo novo (descarta a tela atual, o arquivo já está salvo)"):
                st.session_state.resultado_atual = None
                st.session_state.carimbo_atual = None
                st.session_state.temas = []
                st.rerun()

        with col_refazer:
            # Refaz SÓ o roteiro, mantendo o mesmo tema. Útil quando o
            # roteiro saiu ruim mas o tema é bom - evita ter que buscar
            # tema de novo. Salva num arquivo NOVO (carimbo novo), então a
            # versão anterior não é perdida e dá pra comparar as duas.
            if st.button("🔄 Refazer só o roteiro (mesmo tema, gera versão nova)"):
                log_refazer = st.empty()
                linhas_refazer = []

                def registrar_refazer(msg):
                    linhas_refazer.append(msg)
                    log_refazer.code("\n".join(linhas_refazer[-15:]))

                with st.spinner("Gerando uma nova versão do roteiro..."):
                    import builtins

                    print_original = builtins.print
                    builtins.print = lambda *a, **k: registrar_refazer(
                        " ".join(str(x) for x in a)
                    )
                    try:
                        novo = pipe.gerar_video_completo(resultado["tema"])
                    finally:
                        builtins.print = print_original

                novo_carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
                salvar_json_e_txt(novo, novo_carimbo)
                st.session_state.resultado_atual = novo
                st.session_state.carimbo_atual = novo_carimbo
                st.success(
                    "Nova versão gerada e salva. A versão anterior continua "
                    "na aba 'Vídeos salvos' se quiser comparar."
                )
                st.rerun()

        if resultado.get("pendencias_manuais"):
            st.warning(
                "**O loop de revisão parou com pendência.** O roteiro abaixo "
                "é a MELHOR versão gerada neste run (não necessariamente a "
                "última). Resolva estes pontos no texto antes de gravar:\n\n"
                + resultado["pendencias_manuais"]
            )

        st.text_area(
            "📝 Narração limpa (pronta pra colar no ElevenLabs)",
            resultado["narracao_limpa"],
            height=300,
        )

        if resultado.get("checklist_verificar"):
            sem_respaldo = [
                c for c in pipe.conferir_numeros_contra_dossie(
                    resultado["roteiro"], resultado.get("dossie")
                ) if not c["confere"]
            ]
            titulo_checklist = (
                f"🔎 Checklist dos números - {len(sem_respaldo)} sem respaldo "
                "no material pesquisado"
            )
            with st.expander(titulo_checklist, expanded=bool(sem_respaldo)):
                st.text(resultado["checklist_verificar"])

        if resultado.get("dossie"):
            with st.expander("📚 Dossiê de pesquisa (o que o roteirista leu)"):
                for fonte in resultado["dossie"].get("fontes", []):
                    st.markdown(f"- {fonte}")
                st.text(resultado["dossie"]["texto"])

        with st.expander("Ver roteiro completo, com marcações [VERIFICAR]"):
            st.text(resultado["roteiro"])
            st.warning(
                "Revise todo trecho marcado [VERIFICAR] numa fonte de "
                "verdade ANTES de gravar o áudio."
            )

        with st.expander("🎯 Título, thumbnail, descrição e tags"):
            st.text(resultado["metadados"])

        with st.expander("🖼️ Prompt pro Gemini (foto da thumbnail)"):
            st.text(resultado["prompt_imagem_gemini"])

        with st.expander("📋 Histórico de revisões deste roteiro"):
            for item in resultado.get("historico_revisoes", []):
                emoji = "✅" if item["veredito"] == "aprovado" else "❌"
                st.markdown(f"**{emoji} Tentativa {item['tentativa']}: {item['veredito'].upper()}**")
                if item["veredito"] == "reprovado":
                    st.text(item["mudancas_pedidas"])
                # Sugestões não reprovam mais o roteiro sozinhas (ver
                # filtrar_mudancas_acionaveis no pipeline), mas continuam
                # aqui porque costumam ser um bom ajuste manual.
                for sugestao in item.get("sugestoes_nao_bloqueantes", []):
                    st.caption(f"Sugestão (não reprovou): {sugestao}")

        st.divider()
        st.subheader("2. Próximos passos (cada um é opcional e independente)")

        col_audio, col_broll = st.columns(2)

        with col_audio:
            st.markdown("**🔊 Narração (ElevenLabs - PAGO por caractere)**")
            if not pipe.ELEVENLABS_API_KEY or not pipe.ELEVENLABS_VOICE_ID:
                st.info("ELEVENLABS_API_KEY/VOICE_ID não configurados no .env.")
            else:
                cota = pipe.consultar_cota_elevenlabs()
                if cota:
                    usados, limite = cota
                    st.caption(f"Cota atual: {limite - usados} de {limite} créditos disponíveis.")
                if st.button("Gerar áudio agora (gasta crédito)"):
                    with st.spinner("Gerando áudio..."):
                        caminho_mp3 = PASTA_SAIDAS / f"video_{carimbo}.mp3"
                        audio = pipe.gerar_audio_elevenlabs(
                            resultado["narracao_limpa"],
                            caminho_mp3,
                            pedir_confirmacao=False,
                        )
                    if audio:
                        st.success(f"Áudio salvo em: {audio}")
                        st.audio(audio)
                    else:
                        st.error(
                            "Não gerou áudio - confira o aviso acima ou a "
                            "cota da sua conta ElevenLabs."
                        )

        with col_broll:
            st.markdown("**🎞️ Clipes de b-roll (Pexels - grátis)**")
            if st.button("Baixar clipes agora"):
                with st.spinner("Baixando clipes..."):
                    pasta_broll = PASTA_SAIDAS / f"video_{carimbo}_broll"
                    baixados, pulados = pipe.baixar_broll(
                        resultado["broll"], pasta_broll
                    )
                st.success(f"{len(baixados)} clipe(s) baixado(s) em: {pasta_broll}")
                if pulados:
                    st.warning(f"{len(pulados)} trecho(s) sem clipe - veja o .txt salvo pra detalhes.")

# =========================================================================
# ABA 2 - VÍDEOS SALVOS
# =========================================================================
with aba_salvos:
    arquivos_json = sorted(
        PASTA_SAIDAS.glob("video_*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not arquivos_json:
        st.info("Nenhum vídeo salvo ainda - gere um na aba anterior.")
    for arq in arquivos_json:
        with open(arq, "r", encoding="utf-8") as f:
            dados = json.load(f)
        with st.expander(f"{arq.stem}  -  {dados.get('tema', '(sem tema salvo)')}"):
            st.text(dados.get("narracao_limpa", "")[:400] + "...")
            if st.button("Abrir este roteiro na aba 'Gerar novo vídeo'", key=f"abrir_{arq.name}"):
                if "narracao_limpa" not in dados:
                    dados["narracao_limpa"] = pipe.extrair_narracao_limpa(dados["roteiro"])
                st.session_state.resultado_atual = dados
                st.session_state.carimbo_atual = arq.stem.replace("video_", "")
                st.rerun()

# =========================================================================
# ABA 3 - APRENDIZADO
# =========================================================================
with aba_aprendizado:
    st.subheader("O que o pipeline já aprendeu")
    st.caption(
        "Não é aprendizado de máquina de verdade (o modelo não é "
        "retreinado) - é um contador de quais problemas mais se repetem "
        "nas avaliações, usado pra reforçar automaticamente esses pontos "
        "no próximo roteiro."
    )
    if pipe.CAMINHO_ESTATISTICAS_APRENDIZADO.exists():
        with open(pipe.CAMINHO_ESTATISTICAS_APRENDIZADO, "r", encoding="utf-8") as f:
            stats = json.load(f)
        total = stats.get("total_avaliacoes", 0)
        st.metric("Avaliações registradas até agora", total)
        if total:
            for campo, contagem in stats.get("problemas", {}).items():
                taxa = contagem / total
                st.progress(min(taxa, 1.0), text=f"{campo}: {contagem}/{total} ({taxa*100:.0f}%)")
            st.caption("Acima de 40% (com pelo menos 3 avaliações), o pipeline já reforça esse ponto sozinho.")
    else:
        st.info("Ainda sem histórico - gere e avalie alguns vídeos primeiro.")
