"""
Raio-X de um canal de referência (YouTube Data API v3)
======================================================

PRA QUE SERVE:
    Copiar o estilo de um canal não é olhar 3 vídeos e achar que entendeu.
    Este script puxa TODOS os vídeos de um canal e mede o que de fato define
    o formato dele: duração real dos vídeos, ritmo de postagem, padrão de
    título, tags, tamanho de descrição, e quais vídeos estouraram em relação
    à média do próprio canal (que é o que interessa - "1 milhão de views" não
    quer dizer nada se todo vídeo do canal faz isso).

    O agente 1B do pipeline principal já busca os títulos mais vistos de
    canais de referência. Este script é a versão funda: serve pra você
    dissecar UM canal antes de decidir o formato do seu.

COMO RODAR:
    python raio_x_canal.py @ELALGORITMOOCULTO-95
    python raio_x_canal.py https://www.youtube.com/@ELALGORITMOOCULTO-95
    python raio_x_canal.py            (ele pergunta o canal)

    Opcional, pra limitar quantos vídeos analisar (padrão 300):
    python raio_x_canal.py @canal 100

O QUE PRECISA:
    - YOUTUBE_API_KEY no .env (a mesma do pipeline; é gratuita)
    - pip install requests python-dotenv

CUSTO DE COTA:
    Pouquíssimo. Um canal de 100 vídeos gasta ~10 unidades das 10.000
    diárias gratuitas. Só o modo de busca por nome (usado apenas se o
    @handle não resolver) custa 100 unidades por tentativa.

SAÍDA:
    saidas/raiox_<canal>_<data>.json   -> dados crus completos
    saidas/raiox_<canal>_<data>.txt    -> relatório legível
    E imprime no terminal um bloco resumido, pronto pra copiar e colar
    num chat com uma IA pra pedir análise de formato.
"""

import os
import re
import sys
import json
import unicodedata
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

import requests
from dotenv import load_dotenv

PASTA_DO_SCRIPT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=PASTA_DO_SCRIPT / ".env")

YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# Um vídeo com até 60s e formato vertical entra como Short no YouTube.
# A API não diz "isto é um Short", então a duração é o melhor sinal barato.
LIMITE_SHORT_SEGUNDOS = 60

# Palavras que aparecem em qualquer título e não dizem nada sobre o nicho.
# Cobre PT, ES e EN porque canal de referência raramente é só do seu idioma.
_VAZIAS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos",
    "das", "e", "em", "no", "na", "nos", "nas", "por", "para", "pra", "com",
    "que", "se", "sem", "ao", "aos", "mais", "mas", "ou", "the", "of", "to",
    "in", "on", "at", "for", "and", "is", "it", "this", "that", "you", "your",
    "el", "la", "los", "las", "un", "una", "y", "es", "del", "al", "con",
    "por", "para", "que", "su", "sus", "lo", "como", "mas", "pero", "sobre",
    "ese", "esta", "este", "esa", "todo", "toda", "ser", "sao", "foi", "era",
}


def _sem_acento(texto):
    """'História' -> 'historia'. Junta as contagens de palavra acentuada."""
    normalizado = unicodedata.normalize("NFD", texto)
    return "".join(c for c in normalizado if unicodedata.category(c) != "Mn")


def _youtube_get(endpoint, params):
    params = {**params, "key": YOUTUBE_KEY}
    resp = requests.get(f"{YOUTUBE_API_BASE}/{endpoint}", params=params, timeout=30)
    if resp.status_code == 403:
        raise SystemExit(
            "\nERRO 403 da API do YouTube. As causas, em ordem de frequência:\n"
            "  1. YOUTUBE_API_KEY vazia ou errada no .env\n"
            "  2. A 'YouTube Data API v3' não foi ativada no projeto do Google Cloud\n"
            "  3. Cota diária de 10.000 unidades estourada (zera à meia-noite no Pacífico)\n"
            f"\nResposta crua: {resp.text[:400]}"
        )
    resp.raise_for_status()
    return resp.json()


def normalizar_entrada(bruto):
    """
    Aceita '@canal', 'canal', a URL completa ou o ID (UC...) e devolve
    ('handle'|'id', valor) - porque a API usa parâmetros diferentes pra cada.
    """
    texto = bruto.strip()
    texto = re.sub(r"^https?://(www\.)?youtube\.com/", "", texto)
    texto = texto.split("?")[0]          # tira ?si=... e afins
    if "/" in texto:
        # sobrou "channel/UCxxx" ou "c/NomeDoCanal" - o que importa é o fim
        texto = texto.rstrip("/").split("/")[-1]
    texto = texto.lstrip("@").strip()
    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", texto):
        return "id", texto
    return "handle", texto


def resolver_canal(bruto):
    """Handle/ID/URL -> o registro completo do canal (snippet + estatísticas)."""
    tipo, valor = normalizar_entrada(bruto)
    partes = "snippet,statistics,contentDetails,brandingSettings"

    if tipo == "id":
        dados = _youtube_get("channels", {"part": partes, "id": valor})
    else:
        dados = _youtube_get("channels", {"part": partes, "forHandle": valor})

    itens = dados.get("items", [])
    if itens:
        return itens[0]

    # O @handle não resolveu (handle trocado, canal apagado, erro de digitação).
    # A busca por nome custa 100 unidades de cota, então só entra aqui.
    print(f"  '@{valor}' não resolveu direto - tentando busca por nome (custa mais cota)...")
    busca = _youtube_get(
        "search", {"part": "snippet", "q": valor, "type": "channel", "maxResults": 3}
    )
    achados = busca.get("items", [])
    if not achados:
        raise SystemExit(f"\nNenhum canal encontrado para '{bruto}'.")
    if len(achados) > 1:
        print("  Candidatos encontrados:")
        for i, a in enumerate(achados, 1):
            print(f"    {i}. {a['snippet']['title']} - {a['snippet']['channelId']}")
    canal_id = achados[0]["snippet"]["channelId"]
    print(f"  Usando o primeiro: {achados[0]['snippet']['title']}")
    dados = _youtube_get("channels", {"part": partes, "id": canal_id})
    return dados["items"][0]


def listar_ids_dos_uploads(playlist_uploads, limite):
    """Pagina a playlist automática de uploads até juntar 'limite' IDs."""
    ids = []
    token = None
    while len(ids) < limite:
        params = {"part": "contentDetails", "playlistId": playlist_uploads, "maxResults": 50}
        if token:
            params["pageToken"] = token
        dados = _youtube_get("playlistItems", params)
        for item in dados.get("items", []):
            ids.append(item["contentDetails"]["videoId"])
        token = dados.get("nextPageToken")
        print(f"  ...{len(ids)} vídeos listados", end="\r")
        if not token:
            break
    print()
    return ids[:limite]


def detalhar_videos(video_ids):
    """Busca em lotes de 50 (teto da API) tudo que define o formato do vídeo."""
    videos = []
    for i in range(0, len(video_ids), 50):
        lote = video_ids[i : i + 50]
        dados = _youtube_get(
            "videos",
            {"part": "snippet,statistics,contentDetails", "id": ",".join(lote)},
        )
        for item in dados.get("items", []):
            snip = item["snippet"]
            stats = item.get("statistics", {})
            videos.append(
                {
                    "id": item["id"],
                    "titulo": snip["title"],
                    "publicado_em": snip["publishedAt"],
                    "descricao": snip.get("description", ""),
                    "tags": snip.get("tags", []),
                    "idioma": snip.get("defaultAudioLanguage") or snip.get("defaultLanguage") or "",
                    "duracao_s": duracao_iso_para_segundos(item["contentDetails"]["duration"]),
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "comentarios": int(stats.get("commentCount", 0)),
                    "thumb": (snip.get("thumbnails", {}).get("high") or {}).get("url", ""),
                }
            )
        print(f"  ...{len(videos)} vídeos detalhados", end="\r")
    print()
    return videos


def duracao_iso_para_segundos(iso):
    """'PT8M31S' -> 511. A API só devolve duração nesse formato ISO 8601."""
    m = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    dias, horas, minutos, segundos = (int(v) if v else 0 for v in m.groups())
    return dias * 86400 + horas * 3600 + minutos * 60 + segundos


def _mediana(numeros):
    if not numeros:
        return 0
    ordenados = sorted(numeros)
    meio = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[meio]
    return (ordenados[meio - 1] + ordenados[meio]) / 2


def _num(valor, casas=0):
    """12345 -> '12.345'. Formata só o número (trocar no texto inteiro
    estragaria vírgula de título: 'Ele descobriu, sozinho' viraria 'descobriu.')."""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _mmss(segundos):
    return f"{int(segundos) // 60}m{int(segundos) % 60:02d}s"


def _data(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def analisar(canal, videos):
    """Transforma a lista crua de vídeos nos números que definem o formato."""
    agora = datetime.now(timezone.utc)
    videos = sorted(videos, key=lambda v: v["publicado_em"], reverse=True)

    duracoes = [v["duracao_s"] for v in videos]
    views = [v["views"] for v in videos]
    shorts = [v for v in videos if v["duracao_s"] <= LIMITE_SHORT_SEGUNDOS]
    longos = [v for v in videos if v["duracao_s"] > LIMITE_SHORT_SEGUNDOS]

    # Ritmo de postagem: intervalo típico entre um upload e o seguinte.
    datas = [_data(v["publicado_em"]) for v in videos]
    intervalos = [
        (datas[i] - datas[i + 1]).total_seconds() / 86400 for i in range(len(datas) - 1)
    ]

    # Views por dia desde a publicação - compara vídeo novo com vídeo velho
    # de forma justa (o antigo teve mais tempo pra acumular).
    for v in videos:
        dias_no_ar = max((agora - _data(v["publicado_em"])).total_seconds() / 86400, 1)
        v["dias_no_ar"] = round(dias_no_ar, 1)
        v["views_por_dia"] = round(v["views"] / dias_no_ar, 1)

    mediana_views = _mediana(views)
    for v in videos:
        # "Índice viral": quantas vezes o vídeo bateu a mediana do PRÓPRIO
        # canal. É isso que mostra qual tema/título destoou pra cima.
        v["indice_viral"] = round(v["views"] / mediana_views, 2) if mediana_views else 0

    # Padrão de título: o que se repete nos títulos revela a fórmula do canal.
    palavras = Counter()
    for v in videos:
        for p in re.findall(r"[A-Za-zÀ-ÿ0-9']{3,}", _sem_acento(v["titulo"]).lower()):
            if p not in _VAZIAS:
                palavras[p] += 1

    titulos = [v["titulo"] for v in videos]
    tags = Counter(t.lower() for v in videos for t in v["tags"])
    idiomas = Counter(v["idioma"] for v in videos if v["idioma"])

    def _pct(condicao):
        return round(100 * sum(1 for t in titulos if condicao(t)) / len(titulos), 1) if titulos else 0

    return {
        "canal": {
            "titulo": canal["snippet"]["title"],
            "handle": canal["snippet"].get("customUrl", ""),
            "id": canal["id"],
            "descricao": canal["snippet"].get("description", ""),
            "pais": canal["snippet"].get("country", "(não informado)"),
            "idioma_declarado": canal["snippet"].get("defaultLanguage", "(não informado)"),
            "criado_em": canal["snippet"]["publishedAt"][:10],
            "inscritos": int(canal["statistics"].get("subscriberCount", 0)),
            "views_totais": int(canal["statistics"].get("viewCount", 0)),
            "videos_totais": int(canal["statistics"].get("videoCount", 0)),
            "palavras_chave": canal.get("brandingSettings", {}).get("channel", {}).get("keywords", ""),
        },
        "amostra": {
            "videos_analisados": len(videos),
            "primeiro_upload": videos[-1]["publicado_em"][:10] if videos else "",
            "ultimo_upload": videos[0]["publicado_em"][:10] if videos else "",
            "dias_desde_ultimo": round((agora - datas[0]).total_seconds() / 86400, 1) if datas else 0,
        },
        "formato": {
            "pct_shorts": round(100 * len(shorts) / len(videos), 1) if videos else 0,
            "qtd_shorts": len(shorts),
            "qtd_longos": len(longos),
            "duracao_mediana": _mmss(_mediana(duracoes)),
            "duracao_mediana_longos": _mmss(_mediana([v["duracao_s"] for v in longos])),
            "duracao_min": _mmss(min(duracoes)) if duracoes else "-",
            "duracao_max": _mmss(max(duracoes)) if duracoes else "-",
        },
        "ritmo": {
            "intervalo_mediano_dias": round(_mediana(intervalos), 1),
            "uploads_por_semana": round(7 / _mediana(intervalos), 1) if _mediana(intervalos) else 0,
            "uploads_ultimos_30d": sum(1 for d in datas if (agora - d).days <= 30),
            "uploads_ultimos_90d": sum(1 for d in datas if (agora - d).days <= 90),
        },
        "audiencia": {
            "views_mediana": int(mediana_views),
            "views_media": int(sum(views) / len(views)) if views else 0,
            "views_max": max(views) if views else 0,
            "views_min": min(views) if views else 0,
            "likes_por_1000_views": round(
                1000 * sum(v["likes"] for v in videos) / sum(views), 1
            ) if sum(views) else 0,
            "comentarios_por_1000_views": round(
                1000 * sum(v["comentarios"] for v in videos) / sum(views), 1
            ) if sum(views) else 0,
        },
        "titulos": {
            "tamanho_medio_chars": round(sum(len(t) for t in titulos) / len(titulos), 1) if titulos else 0,
            "pct_com_numero": _pct(lambda t: bool(re.search(r"\d", t))),
            "pct_com_interrogacao": _pct(lambda t: "?" in t),
            "pct_com_palavra_toda_maiuscula": _pct(
                lambda t: bool(re.search(r"\b[A-ZÀ-Ý]{3,}\b", t))
            ),
            "pct_com_separador": _pct(lambda t: any(s in t for s in ("|", "-", ":", "—"))),
            "palavras_mais_usadas": palavras.most_common(30),
        },
        "descricao": {
            "tamanho_mediano_chars": int(_mediana([len(v["descricao"]) for v in videos])),
            "pct_com_link": round(
                100 * sum(1 for v in videos if "http" in v["descricao"]) / len(videos), 1
            ) if videos else 0,
            "pct_com_hashtag": round(
                100 * sum(1 for v in videos if "#" in v["descricao"]) / len(videos), 1
            ) if videos else 0,
            "exemplo": videos[0]["descricao"][:1500] if videos else "",
        },
        "tags_mais_usadas": tags.most_common(25),
        "idiomas_declarados": idiomas.most_common(5),
        "top_por_views": sorted(videos, key=lambda v: v["views"], reverse=True)[:20],
        "top_por_views_por_dia": sorted(videos, key=lambda v: v["views_por_dia"], reverse=True)[:10],
        "piores_por_views": sorted(videos, key=lambda v: v["views"])[:5],
        "ultimos_publicados": videos[:15],
        "todos_os_videos": videos,
    }


def _linha_video(v, i=None):
    prefixo = f"{i:>3}. " if i is not None else "     "
    return (
        f"{prefixo}{v['titulo']}\n"
        f"        {_num(v['views']):>11} views | {_mmss(v['duracao_s']):>7} | "
        f"{v['publicado_em'][:10]} | {_num(v['views_por_dia'], 1):>10} views/dia | "
        f"{v['indice_viral']:>5.2f}x a mediana"
    )


def montar_relatorio(a):
    c, f, r, au, t = a["canal"], a["formato"], a["ritmo"], a["audiencia"], a["titulos"]
    L = []
    L.append("=" * 74)
    L.append(f"RAIO-X DO CANAL: {c['titulo']}")
    L.append("=" * 74)
    L.append(f"Handle .............. {c['handle']}")
    L.append(f"ID .................. {c['id']}")
    L.append(f"País / idioma ....... {c['pais']} / {c['idioma_declarado']}")
    L.append(f"Criado em ........... {c['criado_em']}")
    L.append(f"Inscritos ........... {_num(c['inscritos'])}")
    L.append(f"Views totais ........ {_num(c['views_totais'])}")
    L.append(f"Vídeos no canal ..... {c['videos_totais']}")
    L.append(f"Analisados aqui ..... {a['amostra']['videos_analisados']} "
             f"({a['amostra']['primeiro_upload']} até {a['amostra']['ultimo_upload']})")
    L.append("")
    L.append("DESCRIÇÃO DO CANAL")
    L.append("-" * 74)
    L.append(c["descricao"] or "(vazia)")
    if c["palavras_chave"]:
        L.append(f"\nPalavras-chave do canal: {c['palavras_chave']}")
    L.append("")
    L.append("FORMATO")
    L.append("-" * 74)
    L.append(f"Shorts (até 60s) .......... {f['qtd_shorts']} ({f['pct_shorts']}%)")
    L.append(f"Vídeos longos ............. {f['qtd_longos']}")
    L.append(f"Duração mediana (geral) ... {f['duracao_mediana']}")
    L.append(f"Duração mediana (longos) .. {f['duracao_mediana_longos']}")
    L.append(f"Mais curto / mais longo ... {f['duracao_min']} / {f['duracao_max']}")
    L.append("")
    L.append("RITMO DE POSTAGEM")
    L.append("-" * 74)
    L.append(f"Intervalo mediano ......... {r['intervalo_mediano_dias']} dias "
             f"(~{r['uploads_por_semana']} vídeos/semana)")
    L.append(f"Últimos 30 / 90 dias ...... {r['uploads_ultimos_30d']} / {r['uploads_ultimos_90d']} vídeos")
    L.append(f"Dias desde o último ....... {a['amostra']['dias_desde_ultimo']}")
    L.append("")
    L.append("AUDIÊNCIA")
    L.append("-" * 74)
    L.append(f"Views: mediana {_num(au['views_mediana'])} | média {_num(au['views_media'])} | "
             f"máx {_num(au['views_max'])} | mín {_num(au['views_min'])}")
    L.append(f"Engajamento: {au['likes_por_1000_views']} likes e "
             f"{au['comentarios_por_1000_views']} comentários a cada 1.000 views")
    L.append("")
    L.append("PADRÃO DE TÍTULO")
    L.append("-" * 74)
    L.append(f"Tamanho médio ............. {t['tamanho_medio_chars']} caracteres")
    L.append(f"Com número ................ {t['pct_com_numero']}%")
    L.append(f"Com interrogação .......... {t['pct_com_interrogacao']}%")
    L.append(f"Com PALAVRA MAIÚSCULA ..... {t['pct_com_palavra_toda_maiuscula']}%")
    L.append(f"Com separador (| - :) ..... {t['pct_com_separador']}%")
    L.append("Palavras mais repetidas:")
    L.append("  " + ", ".join(f"{p} ({n})" for p, n in t["palavras_mais_usadas"]))
    L.append("")
    L.append("DESCRIÇÃO DOS VÍDEOS")
    L.append("-" * 74)
    L.append(f"Tamanho mediano ........... {a['descricao']['tamanho_mediano_chars']} caracteres")
    L.append(f"Com link / com hashtag .... {a['descricao']['pct_com_link']}% / {a['descricao']['pct_com_hashtag']}%")
    L.append("Exemplo (vídeo mais recente):")
    L.append(a["descricao"]["exemplo"] or "(vazia)")
    L.append("")
    if a["tags_mais_usadas"]:
        L.append("TAGS MAIS USADAS")
        L.append("-" * 74)
        L.append("  " + ", ".join(f"{t_} ({n})" for t_, n in a["tags_mais_usadas"]))
        L.append("")
    L.append("TOP 20 POR VIEWS")
    L.append("-" * 74)
    for i, v in enumerate(a["top_por_views"], 1):
        L.append(_linha_video(v, i))
    L.append("")
    L.append("TOP 10 POR VIEWS/DIA (o que está funcionando AGORA)")
    L.append("-" * 74)
    for i, v in enumerate(a["top_por_views_por_dia"], 1):
        L.append(_linha_video(v, i))
    L.append("")
    L.append("ÚLTIMOS 15 PUBLICADOS (pra onde o canal está indo)")
    L.append("-" * 74)
    for i, v in enumerate(a["ultimos_publicados"], 1):
        L.append(_linha_video(v, i))
    L.append("")
    L.append("OS 5 QUE MENOS RENDERAM (o que NÃO repetir)")
    L.append("-" * 74)
    for i, v in enumerate(a["piores_por_views"], 1):
        L.append(_linha_video(v, i))
    L.append("")
    L.append("THUMBNAILS DOS 10 MAIORES (abra no navegador pra estudar o visual)")
    L.append("-" * 74)
    for v in a["top_por_views"][:10]:
        L.append(f"  {v['thumb']}  <- {v['titulo'][:55]}")
    return "\n".join(L)


def bloco_para_colar(a):
    """Resumo enxuto: é isto que você cola num chat com IA pra pedir análise."""
    c, f, r, au, t = a["canal"], a["formato"], a["ritmo"], a["audiencia"], a["titulos"]
    L = []
    L.append("----- COLE DAQUI -----")
    L.append(f"CANAL: {c['titulo']} ({c['handle']}) | país {c['pais']} | criado {c['criado_em']}")
    L.append(f"{c['inscritos']} inscritos | {c['videos_totais']} vídeos | {c['views_totais']} views totais")
    L.append(f"DESCRIÇÃO DO CANAL: {(c['descricao'] or '(vazia)')[:400]}")
    L.append(f"FORMATO: {f['pct_shorts']}% Shorts | duração mediana {f['duracao_mediana']} "
             f"(longos: {f['duracao_mediana_longos']}) | de {f['duracao_min']} a {f['duracao_max']}")
    L.append(f"RITMO: ~{r['uploads_por_semana']} vídeos/semana | {r['uploads_ultimos_30d']} nos últimos 30d")
    L.append(f"VIEWS: mediana {au['views_mediana']} | máx {au['views_max']} | "
             f"{au['likes_por_1000_views']} likes/1000 views")
    L.append(f"TÍTULOS: {t['tamanho_medio_chars']} chars | {t['pct_com_numero']}% com número | "
             f"{t['pct_com_interrogacao']}% com '?' | {t['pct_com_palavra_toda_maiuscula']}% com MAIÚSCULA")
    L.append("PALAVRAS MAIS USADAS NOS TÍTULOS: "
             + ", ".join(p for p, _ in t["palavras_mais_usadas"][:20]))
    if a["tags_mais_usadas"]:
        L.append("TAGS: " + ", ".join(t_ for t_, _ in a["tags_mais_usadas"][:15]))
    L.append(f"DESCRIÇÃO DOS VÍDEOS: mediana {a['descricao']['tamanho_mediano_chars']} chars")
    L.append("\nTOP 20 POR VIEWS (título | views | duração | data):")
    for v in a["top_por_views"]:
        L.append(f"- {v['titulo']} | {v['views']} | {_mmss(v['duracao_s'])} | {v['publicado_em'][:10]}")
    L.append("\nÚLTIMOS 15 PUBLICADOS:")
    for v in a["ultimos_publicados"]:
        L.append(f"- {v['titulo']} | {v['views']} | {_mmss(v['duracao_s'])} | {v['publicado_em'][:10]}")
    L.append("----- ATÉ AQUI -----")
    return "\n".join(L)


if __name__ == "__main__":
    if not YOUTUBE_KEY:
        raise SystemExit(
            "\nYOUTUBE_API_KEY não encontrada.\n"
            "Copie o .env.example pra .env e preencha YOUTUBE_API_KEY.\n"
            "A chave é gratuita: console.cloud.google.com -> ative a "
            "'YouTube Data API v3' -> Credenciais -> Chave de API."
        )

    entrada = sys.argv[1] if len(sys.argv) > 1 else input(
        "Canal de referência (@handle, URL ou ID): "
    ).strip()
    limite = int(sys.argv[2]) if len(sys.argv) > 2 else 300

    print(f"\nResolvendo '{entrada}'...")
    canal = resolver_canal(entrada)
    print(f"  Canal: {canal['snippet']['title']}")

    playlist = canal["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"Listando uploads (teto de {limite})...")
    ids = listar_ids_dos_uploads(playlist, limite)
    if not ids:
        raise SystemExit("O canal não tem vídeos públicos listáveis.")

    print("Buscando detalhes de cada vídeo...")
    videos = detalhar_videos(ids)

    print("Analisando...")
    analise = analisar(canal, videos)

    pasta_saidas = PASTA_DO_SCRIPT / "saidas"
    pasta_saidas.mkdir(exist_ok=True)
    apelido = re.sub(r"[^a-z0-9]+", "_", _sem_acento(canal["snippet"]["title"]).lower()).strip("_")[:40]
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho_json = pasta_saidas / f"raiox_{apelido}_{carimbo}.json"
    caminho_txt = pasta_saidas / f"raiox_{apelido}_{carimbo}.txt"

    with open(caminho_json, "w", encoding="utf-8") as fp:
        json.dump(analise, fp, ensure_ascii=False, indent=2)
    with open(caminho_txt, "w", encoding="utf-8") as fp:
        fp.write(montar_relatorio(analise))

    print("\n" + bloco_para_colar(analise) + "\n")
    print("Concluído!")
    print(f"  Relatório legível: {caminho_txt}")
    print(f"  Dados completos:   {caminho_json}")
    print("\nO bloco acima (entre COLE DAQUI e ATÉ AQUI) é o que você cola no chat.")
