"""Halloween Colégio GDV - votação do concurso de fantasias (Streamlit + Google Sheets)."""
import html
import logging
import threading

import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection

logger = logging.getLogger(__name__)

URL_PLANILHA_PADRAO = (
    "https://docs.google.com/spreadsheets/d/"
    "1RGh0FRMgZGJTE-aXWGfHqYsdl0mzxZ5Qr-uXgKtcmmY/edit?gid=0#gid=0"
)

TURMAS = [
    "5º Ano", "6º Ano", "7º Ano", "8º Ano", "9º Ano",
    "1ª Série EM", "2ª Série EM", "3ª Série EM",
]
CRITERIOS = ["Criatividade", "Execução", "Performance", "Adequação ao Tema"]
NOTA_MAX = 2.5  # cada critério vale de 0.0 a 2.5 (total máximo 10.0)
COLUNAS = ["Jurado", "Série/Ano", "Aluno", *CRITERIOS, "Nota Final"]

CSS = """
.hero{background:linear-gradient(135deg,#2A1245 0%,#4B1D7A 60%,#B4520C 140%);border:1px solid rgba(255,122,26,.35);border-radius:16px;padding:1.5rem 1.8rem;margin-bottom:1.1rem}
.hero h1{font-family:'Palatino Linotype',Palatino,Georgia,serif;color:#FFF;margin:0 0 .25rem 0;padding:0;font-size:2.1rem;line-height:1.2}
.hero p{color:#E9DDF5;margin:0}
.badge{display:inline-block;padding:.15rem .75rem;border-radius:999px;font-size:.8rem;font-weight:600;margin-top:.8rem}
.badge.aberta{background:rgba(46,204,113,.15);color:#6EE7A0;border:1px solid rgba(46,204,113,.5)}
.badge.encerrada{background:rgba(255,122,26,.18);color:#FFB070;border:1px solid rgba(255,122,26,.55)}
.badge.parcial{background:rgba(167,125,255,.16);color:#CDB4FF;border:1px solid rgba(167,125,255,.5)}
.stat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.75rem;margin-bottom:1rem}
.stat{background:#221338;border:1px solid #3B2459;border-radius:12px;padding:.75rem 1rem}
.stat .valor{color:#FF9A3D;font-size:1.6rem;font-weight:700;line-height:1.2}
.stat .rotulo{color:#CDBDE0;font-size:.85rem}
.card{background:#221338;border:1px solid #3B2459;border-radius:14px;padding:1rem 1.2rem;margin-bottom:1rem}
.card .titulo{font-family:'Palatino Linotype',Palatino,Georgia,serif;color:#FF9A3D;font-weight:700;font-size:1.15rem;margin-bottom:.3rem}
.card .meta{color:#CDBDE0;font-size:.92rem;margin-bottom:.6rem}
.linha{display:flex;justify-content:space-between;gap:1rem;padding:.35rem 0;border-bottom:1px solid #3B2459;color:#F4EEF9}
.linha.total{border-bottom:none;color:#FFB070;font-size:1.1rem;font-weight:700}
.campeao{background:linear-gradient(135deg,#3A1766,#7A2E0A);border:2px solid #FF9A3D;border-radius:16px;padding:1.2rem 1.5rem;text-align:center;margin-bottom:1rem}
.campeao .selo{font-family:'Palatino Linotype',Palatino,Georgia,serif;color:#FFB070;font-size:1.05rem;font-weight:700}
.campeao .nome{font-family:'Palatino Linotype',Palatino,Georgia,serif;color:#FFF;font-size:1.9rem;font-weight:700;line-height:1.25}
.campeao .sub{color:#EBDDF7}
@media (max-width:640px){.hero h1{font-size:1.55rem}.stat .valor{font-size:1.25rem}.stat-grid{gap:.5rem}.campeao .nome{font-size:1.5rem}}
"""


# ----------------------------------------------------------------------------
# Configuração e utilitários
# ----------------------------------------------------------------------------
def configuracao(chave, padrao=None):
    """Lê um valor de st.secrets sem quebrar se o arquivo de secrets não existir."""
    try:
        return st.secrets.get(chave, padrao)
    except Exception:
        return padrao


def url_planilha():
    return configuracao("planilha_url", URL_PLANILHA_PADRAO)


def conexao():
    return st.connection("gsheets", type=GSheetsConnection)


def esc(texto):
    """Escapa texto digitado pelo usuário antes de inseri-lo em HTML."""
    return html.escape(str(texto))


def fmt(numero, casas=1):
    return f"{numero:.{casas}f}".replace(".", ",")


def limpar_texto(valor, limite=80):
    """Normaliza espaços e remove caracteres que fariam o Sheets interpretar o texto como fórmula."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ""
    texto = " ".join(str(valor).split())
    return texto.lstrip("=+-@")[:limite].strip()


def chave(valor):
    """Chave de comparação: ignora maiúsculas/minúsculas e espaços repetidos."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ""
    return " ".join(str(valor).split()).casefold()


def mostrar_tabela(df):
    try:
        st.dataframe(df, width="stretch", hide_index=True)
    except Exception:  # versões antigas do Streamlit
        st.dataframe(df, use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------
# Dados
# ----------------------------------------------------------------------------
def ler_planilha(ttl):
    df = conexao().read(spreadsheet=url_planilha(), ttl=ttl)
    df = df.dropna(how="all")
    for coluna in COLUNAS:
        if coluna not in df.columns:
            df[coluna] = pd.NA
    return df.reset_index(drop=True)


def preparar_votos(df):
    """Mantém só votos válidos e recalcula a nota final a partir dos critérios."""
    v = df.copy()
    for c in CRITERIOS:
        v[c] = pd.to_numeric(v[c], errors="coerce")
    for c in ["Jurado", "Série/Ano", "Aluno"]:
        v[c] = v[c].map(lambda x: " ".join(str(x).split()) if pd.notna(x) else "")
    validos = (
        v[CRITERIOS].notna().all(axis=1)
        & v[CRITERIOS].ge(0).all(axis=1)
        & v[CRITERIOS].le(NOTA_MAX + 1e-9).all(axis=1)
        & (v["Jurado"] != "")
        & (v["Aluno"] != "")
        & v["Série/Ano"].isin(TURMAS)
    )
    ignorados = int((~validos).sum())
    v = v[validos].copy()
    v["Nota Final"] = v[CRITERIOS].sum(axis=1).round(1)
    return v.reset_index(drop=True), ignorados


def classificar(votos):
    """Ranking pela média da nota final de cada aluno. Empates compartilham a posição."""
    colunas = ["Posição", "Série/Ano", "Aluno", "Média", "Avaliações", "Empate"]
    if votos.empty:
        return pd.DataFrame(columns=colunas)
    v = votos.assign(_k=votos["Aluno"].map(chave))
    g = (
        v.groupby(["Série/Ano", "_k"], sort=False)
        .agg(Aluno=("Aluno", "first"), Média=("Nota Final", "mean"), Avaliações=("Nota Final", "size"))
        .reset_index()
    )
    g["Média"] = g["Média"].round(2)
    g["Posição"] = g["Média"].rank(method="min", ascending=False).astype(int)
    g["Empate"] = g.duplicated("Posição", keep=False)
    g = g.sort_values(["Posição", "Aluno"], key=lambda s: s.map(chave) if s.dtype == object else s)
    return g.reset_index(drop=True)[colunas]


@st.cache_resource
def trava_gravacao():
    return threading.Lock()


def registrar_voto(voto):
    """Grava o voto. Relê a planilha dentro de uma trava para não sobrescrever votos de outros jurados."""
    with trava_gravacao():
        try:
            atual = ler_planilha(ttl=0)
        except Exception:
            logger.exception("Falha ao reler a planilha antes de gravar")
            return "erro_leitura"

        duplicado = (
            (atual["Jurado"].map(chave) == chave(voto["Jurado"]))
            & (atual["Série/Ano"].map(chave) == chave(voto["Série/Ano"]))
            & (atual["Aluno"].map(chave) == chave(voto["Aluno"]))
        ).any()
        if duplicado:
            return "duplicado"

        try:
            novo = pd.DataFrame([voto])
            conexao().update(
                spreadsheet=url_planilha(),
                data=pd.concat([atual, novo], ignore_index=True),
            )
        except Exception:
            logger.exception("Falha ao gravar na planilha")
            return "erro_gravacao"

        st.cache_data.clear()
        return "ok"


# ----------------------------------------------------------------------------
# Estado e ações do formulário
# ----------------------------------------------------------------------------
def inicializar_estado():
    padroes = {"rascunho": None, "aviso": None, "aluno": "", "serie": TURMAS[0]}
    for i in range(len(CRITERIOS)):
        padroes[f"nota_{i}"] = 0.0
    for k, v in padroes.items():
        st.session_state.setdefault(k, v)


def avisar(tipo, mensagem):
    st.session_state["aviso"] = (tipo, mensagem)


def revisar_voto():
    jurado = limpar_texto(st.session_state.get("jurado"))
    aluno = limpar_texto(st.session_state.get("aluno"))
    serie = st.session_state.get("serie")
    notas = {}
    for i, criterio in enumerate(CRITERIOS):
        try:
            notas[criterio] = round(float(st.session_state.get(f"nota_{i}", 0.0)), 1)
        except (TypeError, ValueError):
            notas[criterio] = None

    if not jurado or not aluno:
        avisar("error", "Informe o nome do jurado e o nome do aluno antes de revisar o voto.")
        return
    if serie not in TURMAS:
        avisar("error", "Selecione a série/ano do aluno.")
        return
    if any(n is None or n < 0 or n > NOTA_MAX for n in notas.values()):
        avisar("error", f"Cada nota deve estar entre 0,0 e {fmt(NOTA_MAX)}.")
        return

    st.session_state["rascunho"] = {
        "Jurado": jurado,
        "Série/Ano": serie,
        "Aluno": aluno,
        **notas,
        "Nota Final": round(sum(notas.values()), 1),
    }


def cancelar_revisao():
    st.session_state["rascunho"] = None


def confirmar_voto():
    voto = st.session_state.get("rascunho")
    if not voto:
        return
    resultado = registrar_voto(voto)
    if resultado == "ok":
        avisar("success", f"Voto registrado: {voto['Aluno']} ({voto['Série/Ano']}), "
                          f"total de {fmt(voto['Nota Final'])} pontos.")
        st.session_state["rascunho"] = None
        st.session_state["aluno"] = ""
        for i in range(len(CRITERIOS)):
            st.session_state[f"nota_{i}"] = 0.0
    elif resultado == "duplicado":
        avisar("warning", f"{voto['Jurado']} já avaliou {voto['Aluno']} ({voto['Série/Ano']}). "
                          "O voto não foi gravado novamente. Para corrigir uma nota, fale com a organização.")
        st.session_state["rascunho"] = None
    else:
        avisar("error", "Não foi possível gravar o voto agora. Nada foi perdido: confira os dados "
                        "e clique em Confirmar voto novamente.")


# ----------------------------------------------------------------------------
# Interface
# ----------------------------------------------------------------------------
def html_cabecalho(encerrada):
    if encerrada:
        selo = '<span class="badge encerrada">Votação encerrada</span>'
    else:
        selo = '<span class="badge aberta">Votação aberta</span>'
    return (
        '<div class="hero"><h1>Halloween Colégio GDV</h1>'
        "<p>Concurso de fantasias. Avalie cada aluno nos quatro critérios, revise as notas e confirme o voto.</p>"
        f"{selo}</div>"
    )


def html_resumo(votos, ranking):
    jurados = votos["Jurado"].map(chave).nunique() if not votos.empty else 0
    itens = [(len(votos), "avaliações registradas"), (jurados, "jurados que já votaram"),
             (len(ranking), "alunos avaliados")]
    cartoes = "".join(
        f'<div class="stat"><div class="valor">{n}</div><div class="rotulo">{r}</div></div>' for n, r in itens
    )
    return f'<div class="stat-grid">{cartoes}</div>'


def html_revisao(v):
    linhas = "".join(
        f'<div class="linha"><span>{esc(c)}</span><span>{fmt(v[c])}</span></div>' for c in CRITERIOS
    )
    return (
        '<div class="card"><div class="titulo">Revise antes de confirmar</div>'
        f'<div class="meta">Aluno: {esc(v["Aluno"])}. Série/ano: {esc(v["Série/Ano"])}. '
        f'Jurado: {esc(v["Jurado"])}.</div>{linhas}'
        f'<div class="linha total"><span>Nota total</span><span>{fmt(v["Nota Final"])} / 10,0</span></div></div>'
    )


def html_criterios():
    linhas = "".join(
        f'<div class="linha"><span>{esc(c)}</span><span>0,0 a {fmt(NOTA_MAX)}</span></div>' for c in CRITERIOS
    )
    return (
        '<div class="card"><div class="titulo">Critérios de avaliação</div>'
        f'{linhas}<div class="linha total"><span>Total máximo</span><span>10,0</span></div></div>'
    )


def html_campeao(linha, empate):
    selo = "Empate no 1º lugar" if empate else "Campeão do Halloween"
    return (
        f'<div class="campeao"><div class="selo">{selo}</div>'
        f'<div class="nome">{esc(linha["Aluno"])}</div>'
        f'<div class="sub">{esc(linha["Série/Ano"])}. Média {fmt(linha["Média"], 2)} '
        f'em {int(linha["Avaliações"])} avaliações</div></div>'
    )


def aba_votacao(votos, encerrada):
    col_form, col_info = st.columns([3, 2], gap="large")
    em_revisao = st.session_state["rascunho"] is not None
    jurados = [limpar_texto(j) for j in list(configuracao("jurados", []) or [])]

    with col_form:
        if encerrada:
            st.warning("A votação foi encerrada pela organização. Não é mais possível registrar avaliações.")
            return
        with st.form("form_votacao", clear_on_submit=False):
            if jurados:
                st.selectbox("Jurado", jurados, index=None, placeholder="Selecione seu nome",
                             key="jurado", disabled=em_revisao)
            else:
                st.text_input("Nome do jurado", key="jurado", disabled=em_revisao)
            st.selectbox("Série/ano do aluno", TURMAS, key="serie", disabled=em_revisao)
            st.text_input("Nome do aluno", key="aluno", disabled=em_revisao)
            st.caption(f"Cada critério vale de 0,0 a {fmt(NOTA_MAX)}. A nota total aparece na revisão.")
            c1, c2 = st.columns(2)
            for i, criterio in enumerate(CRITERIOS):
                with (c1 if i % 2 == 0 else c2):
                    st.number_input(criterio, min_value=0.0, max_value=NOTA_MAX, step=0.1,
                                    format="%.1f", key=f"nota_{i}", disabled=em_revisao)
            st.form_submit_button("Revisar voto", type="primary", on_click=revisar_voto,
                                  disabled=em_revisao)

        if em_revisao:
            st.markdown(html_revisao(st.session_state["rascunho"]), unsafe_allow_html=True)
            b1, b2 = st.columns(2)
            b1.button("Confirmar voto", type="primary", on_click=confirmar_voto)
            b2.button("Voltar e editar", on_click=cancelar_revisao)

    with col_info:
        st.markdown(html_criterios(), unsafe_allow_html=True)
        jurado = limpar_texto(st.session_state.get("jurado"))
        if jurado and not votos.empty:
            n = int((votos["Jurado"].map(chave) == chave(jurado)).sum())
            st.caption(f"Avaliações já registradas por {jurado}: {n}")


def aba_classificacao(votos, encerrada, ignorados):
    filtro = st.selectbox("Filtrar por série/ano", ["Todas", *TURMAS], key="filtro")
    dados = votos if filtro == "Todas" else votos[votos["Série/Ano"] == filtro]
    ranking = classificar(dados)

    if ranking.empty:
        st.info("Nenhum voto registrado para este filtro ainda.")
        return

    if encerrada:
        lideres = ranking[ranking["Posição"] == 1]
        for _, linha in lideres.iterrows():
            st.markdown(html_campeao(linha, empate=len(lideres) > 1), unsafe_allow_html=True)
    else:
        st.markdown('<span class="badge parcial">Classificação parcial</span>', unsafe_allow_html=True)
        st.caption("O campeão será divulgado quando a organização encerrar a votação.")

    exibir = ranking.assign(Observação=ranking["Empate"].map({True: "Empate", False: ""})).drop(columns="Empate")
    mostrar_tabela(exibir)
    st.caption("A classificação usa a média das notas totais recebidas por cada aluno. "
               "Alunos com a mesma média dividem a posição.")

    with st.expander("Ver notas por critério"):
        detalhe = dados[["Série/Ano", "Aluno", *CRITERIOS, "Nota Final"]].sort_values("Aluno", key=lambda s: s.map(chave))
        mostrar_tabela(detalhe)

    if ignorados:
        st.caption(f"{ignorados} linha(s) da planilha com dados incompletos ou fora dos limites "
                   "foram ignoradas na apuração.")


def main():
    st.set_page_config(page_title="Halloween Colégio GDV", page_icon="🎃", layout="wide")
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
    inicializar_estado()

    encerrada = bool(configuracao("votacao_encerrada", False))
    st.markdown(html_cabecalho(encerrada), unsafe_allow_html=True)

    try:
        bruto = ler_planilha(ttl=10)
    except Exception:
        logger.exception("Falha ao ler a planilha de votos")
        st.error("Não foi possível acessar a planilha de votos agora. Nenhum dado foi alterado. "
                 "Atualize a página em instantes ou avise a organização.")
        st.stop()

    votos, ignorados = preparar_votos(bruto)
    ranking_geral = classificar(votos)
    st.markdown(html_resumo(votos, ranking_geral), unsafe_allow_html=True)

    aviso = st.session_state.pop("aviso", None)
    if aviso:
        getattr(st, aviso[0])(aviso[1])

    aba1, aba2 = st.tabs(["Avaliar aluno", "Classificação"])
    with aba1:
        aba_votacao(votos, encerrada)
    with aba2:
        aba_classificacao(votos, encerrada, ignorados)


main()
