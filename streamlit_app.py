from pathlib import Path

import pandas as pd
import streamlit as st

from dje_finder.config import Config
from dje_finder.search import (
    MATCH_ALL_TERMS,
    MATCH_EXACT_PHRASE,
    MATCH_NEAR_CONTEXT,
    PDFSearchEngine,
    SORT_NEWEST,
    SORT_OLDEST,
    SORT_RELEVANCE,
)


SORT_OPTIONS = {
    "Relevancia": SORT_RELEVANCE,
    "Mais recentes": SORT_NEWEST,
    "Mais antigos": SORT_OLDEST,
}
MATCH_OPTIONS = {
    "Todos os termos": MATCH_ALL_TERMS,
    "Frase exata": MATCH_EXACT_PHRASE,
    "Contexto proximo": MATCH_NEAR_CONTEXT,
}
DISTANCE_OPTIONS = {
    "25 palavras": 25,
    "50 palavras": 50,
    "100 palavras": 100,
    "200 palavras": 200,
}
PAGE_SIZE = 50


def configure_data_dir(data_dir):
    base_dir = Path(data_dir).expanduser()
    Config.BASE_DIR = base_dir
    Config.INDEX_FILE = base_dir / "indice.json"
    Config.STATE_FILE = base_dir / "estado.json"
    Config.DB_FILE = base_dir / "dje_finder.db"


def db_exists():
    return Config.DB_FILE.exists()


def result_rows(results):
    return [
        {
            "Arquivo": f"{Config.BASE_URL.format(result.date_str)}?label=DJE {result.display_date}",
            "Trecho": result.snippet.replace("[", "").replace("]", ""),
        }
        for result in results
    ]


def render_main_filters():
    query = st.text_input("", placeholder="Informe um termo para busca no DJE")
    related_query = st.text_input("Contexto", placeholder="Informe um segundo termo para busca no DJE (Opcional)")

    cols = st.columns([3, 2])
    with cols[0]:
        match_label = st.selectbox("Modo", list(MATCH_OPTIONS.keys()), index=0)
    with cols[1]:
        distance_label = st.select_slider(
            "Distancia do contexto",
            options=list(DISTANCE_OPTIONS.keys()),
            value="50 palavras",
            help="Usada quando o campo 'Perto de' esta preenchido ou o modo e Contexto proximo.",
        )

    return query, related_query, match_label, distance_label


def render_sidebar_filters(engine, year_options):
    st.sidebar.header("Filtros")
    year_options = ["Todos"] + year_options if year_options else ["Todos"]

    year_filter = st.sidebar.selectbox("Ano", year_options, index=0)
    month_options = engine.get_available_months(year_filter if year_filter != "Todos" else None)
    month_options = ["Todos"] + month_options if month_options else ["Todos"]

    month_filter = st.sidebar.selectbox("Mes", month_options, index=0)
    sort_label = st.sidebar.selectbox("Ordenar", list(SORT_OPTIONS.keys()), index=1)

    view_mode = st.sidebar.radio("Exibir como", ["Tabela", "Lista", "Cartões"], index=0)

    return year_filter, month_filter, sort_label, view_mode


def render_search(engine, filters):
    if "offset" not in st.session_state:
        st.session_state.offset = 0
    if "last_search_key" not in st.session_state:
        st.session_state.last_search_key = None

    query, related_query, match_label, distance_label, year_filter, month_filter, sort_label, view_mode = filters

    search_key = (
        query.strip(),
        related_query.strip(),
        year_filter.strip(),
        month_filter.strip(),
        match_label,
        sort_label,
        distance_label,
    )
    if search_key != st.session_state.last_search_key:
        st.session_state.offset = 0
        st.session_state.last_search_key = search_key

    if not query.strip():
        st.info("Digite um termo principal na tela principal para iniciar a busca.")
        return

    year = year_filter.strip() if year_filter.strip().isdigit() else None
    month = month_filter.strip() if month_filter.strip().isdigit() else None
    match_mode = MATCH_OPTIONS[match_label]
    if related_query.strip():
        match_mode = MATCH_NEAR_CONTEXT

    response = engine.search(
        query=query,
        year=year,
        month=month,
        sort=SORT_OPTIONS[sort_label],
        offset=st.session_state.offset,
        limit=PAGE_SIZE,
        match_mode=match_mode,
        related_query=related_query.strip() or None,
        context_distance=DISTANCE_OPTIONS[distance_label],
    )

    if response.total:
        current_end = response.offset + len(response.results)
        st.subheader(f"Exibindo {response.offset + 1}-{current_end} de {response.total} resultado(s)")
    else:
        st.subheader("0 resultado(s)")

    if response.has_pending_indexing:
        pending = response.total_pdfs - response.indexed_pdfs
        st.warning(
            f"Ainda existem {pending} PDF(s) pendente(s) de indexacao. "
            "A busca pode nao cobrir toda a base."
        )

    if not response.results:
        st.info("Nenhum resultado encontrado para os filtros atuais.")
        return

    # Renderizar conforme o modo selecionado
    if view_mode == "Tabela":
        table = pd.DataFrame(result_rows(response.results))
        st.dataframe(
            table,
            hide_index=True,
            use_container_width=True,
            height=min(620, 38 + (len(response.results) + 1) * 35),
            column_config={
                "Trecho": st.column_config.TextColumn("Trecho", width="large", alignment="left"),
                "Arquivo": st.column_config.LinkColumn(
                    "Arquivo",
                    width="small",
                    alignment="center",
                    display_text=r"^.*label=(.*)$",
                ),
            },
        )
    elif view_mode == "Lista":
        # Lista refinada: data (link) à esquerda, trecho à direita, com separador
        st.markdown("<div style='margin-bottom:8px;'><strong>Resultados</strong></div>", unsafe_allow_html=True)
        for result in response.results:
            url = f"{Config.BASE_URL.format(result.date_str)}?label=DJE {result.display_date}"
            cols = st.columns([1.2, 8.8])
            cols[0].markdown(
                f'<a href="{url}" target="_blank" rel="noopener noreferrer">DJE {result.display_date}</a>',
                unsafe_allow_html=True,
            )
            cols[1].markdown(result.snippet.replace("[", "").replace("]", ""))
            st.markdown("<hr style='border-color: rgba(255,255,255,0.04);'/>", unsafe_allow_html=True)
    else:  # Cartões
        # Cartões responsivos: 2 colunas por linha, cada cartão com link e trecho
        card_style = (
            "border:1px solid rgba(255,255,255,0.06); padding:12px; border-radius:8px;"
            " background: rgba(255,255,255,0.01); margin-bottom:12px;"
        )
        for i in range(0, len(response.results), 2):
            pair = response.results[i : i + 2]
            cols = st.columns(2)
            for j, result in enumerate(pair):
                url = f"{Config.BASE_URL.format(result.date_str)}?label=DJE {result.display_date}"
                html = (
                    f"<div style=\"{card_style}\">"
                    f"<div style='margin-bottom:6px; font-weight:600;'><a href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\">DJE {result.display_date}</a></div>"
                    f"<div style='color: #c9c9c9; margin-bottom:8px;'>{result.snippet.replace('[', '').replace(']', '')}</div>"
                    f"<div><a href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\">Abrir documento</a></div>"
                    f"</div>"
                )
                cols[j].markdown(html, unsafe_allow_html=True)

    nav_cols = st.columns([1, 1, 6])
    if nav_cols[0].button("Anterior", disabled=response.offset == 0):
        st.session_state.offset = max(0, response.offset - PAGE_SIZE)
        st.rerun()
    if nav_cols[1].button("Proxima", disabled=not response.has_more):
        st.session_state.offset = response.offset + len(response.results)
        st.rerun()


def main():
    st.set_page_config(page_title="Buscador DJE", layout="wide")
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&display=swap');
        h1, h2, h3, h4, h5, h6 {
            font-family: 'Orbitron', 'Segoe UI', sans-serif !important;
        }
        /* Header card */
        .hero-card {
            text-align: center;
            padding: 0.8rem 1.4rem 0.75rem;
            margin: 0 0 0.8rem;
            border-radius: 20px;
            background: linear-gradient(135deg, rgba(79, 70, 229, 0.16), rgba(6, 182, 212, 0.12), rgba(16, 185, 129, 0.14));
            border: 1px solid rgba(255, 255, 255, 0.12);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.18);
        }
        .hero-card h1 {
            font-size: 2.35rem;
            font-weight: 900;
            margin: 0;
            line-height: 1;
            letter-spacing: 0.08em;
            background: linear-gradient(90deg, #4f46e5, #06b6d4, #10b981);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        /* DataFrame tweaks: center headers only; make Arquivo column fit content */
        [data-testid="stDataFrameContainer"] table thead th,
        [data-testid="stDataFrame"] table thead th {
            text-align: center !important;
        }

        /* Keep first column (Arquivo) centered */
        [data-testid="stDataFrameContainer"] table tbody td:first-child,
        [data-testid="stDataFrame"] table tbody td:first-child {
            text-align: center !important;
            white-space: nowrap !important;
        }

        /* Make last column (Trecho) left-aligned */
        [data-testid="stDataFrameContainer"] table tbody td:last-child,
        [data-testid="stDataFrame"] table tbody td:last-child {
            text-align: left !important;
            white-space: normal !important;
        }

        /* Fix Arquivo column width to roughly 16 characters */
        [data-testid="stDataFrameContainer"] table tbody td:first-child,
        [data-testid="stDataFrame"] table tbody td:first-child {
            text-align: center !important;
            white-space: nowrap !important;
            width: 16ch !important;
            max-width: 16ch !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }

        /* Use fixed table layout to avoid extra empty column when autosizing */
        [data-testid="stDataFrameContainer"] table,
        [data-testid="stDataFrame"] table {
            table-layout: fixed !important;
            width: 100% !important;
            border-collapse: collapse !important;
        }

        /* Hide completely empty header/cells to collapse any phantom column */
        [data-testid="stDataFrameContainer"] table thead th:empty,
        [data-testid="stDataFrame"] table thead th:empty,
        [data-testid="stDataFrameContainer"] table tbody td:empty,
        [data-testid="stDataFrame"] table tbody td:empty {
            display: none !important;
            padding: 0 !important;
            border: none !important;
        }

        /* Remove rightmost border on last visible cell to avoid thin gap */
        [data-testid="stDataFrameContainer"] table tbody td:last-child,
        [data-testid="stDataFrame"] table tbody td:last-child {
            border-right: none !important;
        }
        </style>
        <div class="hero-card">
            <h1>Buscador DJE</h1>
        </div>
        """,
        unsafe_allow_html=True,
    )
    configure_data_dir(Config.BASE_DIR)

    engine = PDFSearchEngine(page_size=PAGE_SIZE)
    year_options = engine.get_available_years() if db_exists() else []

    filters_main = render_main_filters()
    with st.sidebar:
        filters_sidebar = render_sidebar_filters(engine, year_options)

    filters = (*filters_main, *filters_sidebar)

    if not db_exists():
        st.error("Banco SQLite nao encontrado.")
        st.info(
            "Execute a sincronizacao/indexacao pelo app desktop antes de usar a interface Web."
        )
        return

    render_search(PDFSearchEngine(page_size=PAGE_SIZE), filters)


if __name__ == "__main__":
    main()
