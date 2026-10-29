"""Halloween Colégio GDV - votação de fantasias (Streamlit + Supabase)."""
import html
import logging
import threading
import unicodedata

import pandas as pd
import requests
import streamlit as st

logger = logging.getLogger(__name__)

TURMAS = [
    "5º Ano", "6º Ano", "7º Ano", "8º Ano", "9º Ano",
    "1ª Série EM", "2ª Série EM", "3ª Série EM",
]
# nome na tela -> coluna no banco
CRITERIOS = {
    "Criatividade": "criatividade",
    "Execução": "execucao",
    "Performance": "performance",
    "Adequação ao Tema": "adequacao",
}
NOTA_MAX = 2.5

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
# Utilitários
# ----------------------------------------------------------------------------
def segredo(nome, padrao=None):
    try:
        return st.secrets.get(nome, padrao)
    except Exception:
        return padrao


def esc(texto):
    return html.escape(str(texto))


def fmt(numero, casas=1):
    return f"{numero:.{casas}f}".replace(".", ",")


def limpar_texto(valor, limite=80):
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ""
    return " ".join(str(valor).split()).lstrip("=+-@")[:limite].strip()


def chave(valor):
    """Chave de comparação: sem acentos, sem maiúsculas, sem espaços repetidos."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ""
    texto = unicodedata.normalize("NFKD", " ".join(str(valor).split()))
    return "".join(c for c in texto if not unicodedata.combining(c)).casefold()


def mostrar_tabela(df):
    try:
        st.dataframe(df, width="stretch", hide_index=True)
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------
# Armazenamento
# ----------------------------------------------------------------------------
# Voto repetido é sinalizado com FileExistsError (exceção nativa): classes definidas aqui
# seriam recriadas a cada execução do script e não seriam reconhecidas pelo objeto em cache.


class Supabase:
    """Banco real. A regra de voto único é garantida por uma restrição UNIQUE na tabela."""

    def __init__(self, url, chave_api):
        self.url = url.rstrip("/") + "/rest/v1/votos"
        self.headers = {"apikey": chave_api, "Content-Type": "application/json"}
        if chave_api.startswith("eyJ"):  # chave no formato antigo (JWT)
            self.headers["Authorization"] = f"Bearer {chave_api}"

    def listar(self):
        linhas, inicio = [], 0
        while True:
            r = requests.get(
                self.url, headers=self.headers, timeout=15,
                params={"select": "jurado,serie,aluno," + ",".join(CRITERIOS.values()),
                        "order": "id", "limit": 1000, "offset": inicio},
            )
            if r.status_code != 200:
                raise RuntimeError(f"Leitura falhou: HTTP {r.status_code}")
            lote = r.json()
            linhas += lote
            if len(lote) < 1000:
                return linhas
            inicio += 1000

    def inserir(self, voto):
        r = requests.post(self.url, json=voto, timeout=15,
                          headers={**self.headers, "Prefer": "return=minimal"})
        if r.status_code == 409:
            raise FileExistsError()
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(f"Gravação falhou: HTTP {r.status_code}")


class Memoria:
    """Só para demonstração: os votos somem quando o app reinicia."""

    def __init__(self):
        self.linhas = []
        self.trava = threading.Lock()

    def listar(self):
        return list(self.linhas)

    def inserir(self, voto):
        with self.trava:
            if any((l["jurado_chave"], l["serie"], l["aluno_chave"]) ==
                   (voto["jurado_chave"], voto["serie"], voto["aluno_chave"]) for l in self.linhas):
                raise FileExistsError()
            self.linhas.append(dict(voto))


@st.cache_resource
def armazenamento():
    url, chave_api = segredo("supabase_url"), segredo("supabase_chave")
    if url and chave_api:
        return Supabase(str(url), str(chave_api)), False
    return Memoria(), True


@st.cache_data(ttl=10)
def carregar(_arm):
    return _arm.listar()


# ----------------------------------------------------------------------------
# Apuração
# ----------------------------------------------------------------------------
def preparar_votos(linhas):
    colunas = ["Jurado", "Série/Ano", "Aluno", *CRITERIOS, "Nota Final"]
    if not linhas:
        return pd.DataFrame(columns=colunas), 0
    v = pd.DataFrame(linhas).rename(columns={"jurado": "Jurado", "serie": "Série/Ano", "aluno": "Aluno",
                                              **{b: n for n, b in CRITERIOS.items()}})
    for c in CRITERIOS:
        v[c] = pd.to_numeric(v.get(c), errors="coerce")
    validos = (v[list(CRITERIOS)].notna().all(axis=1)
               & v[list(CRITERIOS)].ge(0).all(axis=1)
               & v[list(CRITERIOS)].le(NOTA_MAX + 1e-9).all(axis=1)
               & v["Série/Ano"].isin(TURMAS))
    ignorados = int((~validos).sum())
    v = v[validos].copy()
    v["Nota Final"] = v[list(CRITERIOS)].sum(axis=1).round(1)
    return v[colunas].reset_index(drop=True), ignorados


def classificar(votos):
    colunas = ["Posição", "Série/Ano", "Aluno", "Média", "Avaliações", "Empate"]
    if votos.empty:
        return pd.DataFrame(columns=colunas)
    v = votos.assign(_k=votos["Aluno"].map(chave))
    g = (v.groupby(["Série/Ano", "_k"], sort=False)
         .agg(Aluno=("Aluno", "first"), Média=("Nota Final", "mean"), Avaliações=("Nota Final", "size"))
         .reset_index())
    g["Média"] = g["Média"].round(2)
    g["Posição"] = g["Média"].rank(method="min", ascending=False).astype(int)
    g["Empate"] = g.duplicated("Posição", keep=False)
    g = g.sort_values(["Posição", "Aluno"], key=lambda s: s.map(chave) if s.dtype == object else s)
    return g.reset_index(drop=True)[colunas]


# ----------------------------------------------------------------------------
# Ações do formulário
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
    for i, nome in enumerate(CRITERIOS):
        try:
            notas[nome] = round(float(st.session_state.get(f"nota_{i}", 0.0)), 1)
        except (TypeError, ValueError):
            notas[nome] = None
    if not jurado or not aluno:
        avisar("error", "Informe o nome do jurado e o nome do aluno antes de revisar o voto.")
    elif serie not in TURMAS:
        avisar("error", "Selecione a série/ano do aluno.")
    elif any(n is None or n < 0 or n > NOTA_MAX for n in notas.values()):
        avisar("error", f"Cada nota deve estar entre 0,0 e {fmt(NOTA_MAX)}.")
    else:
        st.session_state["rascunho"] = {"Jurado": jurado, "Série/Ano": serie, "Aluno": aluno,
                                        **notas, "Nota Final": round(sum(notas.values()), 1)}


def cancelar_revisao():
    st.session_state["rascunho"] = None


def confirmar_voto():
    r = st.session_state.get("rascunho")
    if not r:
        return
    arm, _ = armazenamento()
    payload = {
        "jurado": r["Jurado"], "jurado_chave": chave(r["Jurado"]),
        "serie": r["Série/Ano"],
        "aluno": r["Aluno"], "aluno_chave": chave(r["Aluno"]),
        **{coluna: r[nome] for nome, coluna in CRITERIOS.items()},
    }
    try:
        arm.inserir(payload)
    except FileExistsError:
        avisar("warning", f"{r['Jurado']} já avaliou {r['Aluno']} ({r['Série/Ano']}). O voto não foi gravado "
                          "de novo. Para corrigir uma nota, fale com a organização.")
        st.session_state["rascunho"] = None
    except Exception:
        logger.exception("Falha ao gravar o voto")
        avisar("error", "Não foi possível gravar o voto agora. Os dados continuam na tela: "
                        "clique em Confirmar voto novamente.")
    else:
        carregar.clear()
        avisar("success", f"Voto registrado: {r['Aluno']} ({r['Série/Ano']}), "
                          f"total de {fmt(r['Nota Final'])} pontos.")
        st.session_state["rascunho"] = None
        st.session_state["aluno"] = ""
        for i in range(len(CRITERIOS)):
            st.session_state[f"nota_{i}"] = 0.0


# ----------------------------------------------------------------------------
# Interface
# ----------------------------------------------------------------------------
def html_cabecalho(encerrada):
    selo = ('<span class="badge encerrada">Votação encerrada</span>' if encerrada
            else '<span class="badge aberta">Votação aberta</span>')
    return ('<div class="hero"><h1>Halloween Colégio GDV</h1>'
            "<p>Concurso de fantasias. Avalie o aluno nos quatro critérios, revise as notas e confirme o voto.</p>"
            f"{selo}</div>")


def html_resumo(votos, ranking):
    jurados = votos["Jurado"].map(chave).nunique() if not votos.empty else 0
    itens = [(len(votos), "avaliações registradas"), (jurados, "jurados que já votaram"),
             (len(ranking), "alunos avaliados")]
    return '<div class="stat-grid">' + "".join(
        f'<div class="stat"><div class="valor">{n}</div><div class="rotulo">{r}</div></div>'
        for n, r in itens) + "</div>"


def html_revisao(v):
    linhas = "".join(f'<div class="linha"><span>{esc(c)}</span><span>{fmt(v[c])}</span></div>'
                     for c in CRITERIOS)
    return ('<div class="card"><div class="titulo">Revise antes de confirmar</div>'
            f'<div class="meta">Aluno: {esc(v["Aluno"])}. Série/ano: {esc(v["Série/Ano"])}. '
            f'Jurado: {esc(v["Jurado"])}.</div>{linhas}'
            f'<div class="linha total"><span>Nota total</span><span>{fmt(v["Nota Final"])} / 10,0</span></div></div>')


def html_criterios():
    linhas = "".join(f'<div class="linha"><span>{esc(c)}</span><span>0,0 a {fmt(NOTA_MAX)}</span></div>'
                     for c in CRITERIOS)
    return ('<div class="card"><div class="titulo">Critérios de avaliação</div>'
            f'{linhas}<div class="linha total"><span>Total máximo</span><span>10,0</span></div></div>')


def html_campeao(linha, empate):
    selo = "Empate no 1º lugar" if empate else "Campeão do Halloween"
    return (f'<div class="campeao"><div class="selo">{selo}</div>'
            f'<div class="nome">{esc(linha["Aluno"])}</div>'
            f'<div class="sub">{esc(linha["Série/Ano"])}. Média {fmt(linha["Média"], 2)} '
            f'em {int(linha["Avaliações"])} avaliações</div></div>')


def aba_votacao(votos, encerrada):
    col_form, col_info = st.columns([3, 2], gap="large")
    em_revisao = st.session_state["rascunho"] is not None
    jurados = [limpar_texto(j) for j in list(segredo("jurados", []) or [])]

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
            for i, nome in enumerate(CRITERIOS):
                with (c1 if i % 2 == 0 else c2):
                    st.number_input(nome, min_value=0.0, max_value=NOTA_MAX, step=0.1, format="%.1f",
                                    key=f"nota_{i}", disabled=em_revisao)
            st.form_submit_button("Revisar voto", type="primary", on_click=revisar_voto, disabled=em_revisao)

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
    st.caption("A classificação usa a média das notas totais de cada aluno. Médias iguais dividem a posição.")

    with st.expander("Ver notas por critério"):
        detalhe = dados[["Série/Ano", "Aluno", *CRITERIOS, "Nota Final"]]
        mostrar_tabela(detalhe.sort_values("Aluno", key=lambda s: s.map(chave)))
    if ignorados:
        st.caption(f"{ignorados} registro(s) inválido(s) foram ignorados na apuração.")


def main():
    st.set_page_config(page_title="Halloween Colégio GDV", page_icon="🎃", layout="wide")
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
    inicializar_estado()

    encerrada = bool(segredo("votacao_encerrada", False))
    st.markdown(html_cabecalho(encerrada), unsafe_allow_html=True)

    arm, demonstracao = armazenamento()
    if demonstracao:
        st.warning("Modo demonstração: o banco de dados ainda não foi configurado. Os votos desta tela "
                   "são apagados quando o app reinicia. Não use assim no dia do evento.")
    try:
        linhas = carregar(arm)
    except Exception:
        logger.exception("Falha ao ler os votos")
        st.error("Não foi possível acessar o banco de votos agora. Nenhum dado foi alterado. "
                 "Atualize a página em instantes ou avise a organização.")
        st.stop()

    votos, ignorados = preparar_votos(linhas)
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
