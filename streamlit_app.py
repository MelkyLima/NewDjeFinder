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
            "Data": result.display_date,
            "Ano/Mes": f"{result.year}/{result.month}",
            "Trecho": result.snippet.replace("[", "").replace("]", ""),
            "Arquivo": result.pdf_path.name,
            "Caminho": str(result.pdf_path),
        }
        for result in results
    ]


def render_main_filters():
    st.header("Busca")
    query = st.text_input("Termo principal", placeholder="Ex.: melquizedeque lima pereira")
    related_query = st.text_input("Perto de", placeholder="Ex.: elogiar")

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


def render_sidebar_filters():
    st.sidebar.header("Filtros")
    year_filter = st.sidebar.text_input("Ano", placeholder="Todos")
    month_filter = st.sidebar.text_input("Mes", placeholder="Todos")
    sort_label = st.sidebar.selectbox("Ordenar", list(SORT_OPTIONS.keys()), index=0)

    return year_filter, month_filter, sort_label


def render_download_picker(results):
    options = {
        f"{result.display_date} - {result.pdf_path.name}": result
        for result in results
        if result.pdf_path.is_file()
    }
    if not options:
        return

    with st.expander("Baixar PDF"):
        selected = st.selectbox("Resultado", list(options.keys()))
        result = options[selected]
        with result.pdf_path.open("rb") as pdf_file:
            st.download_button(
                "Baixar PDF selecionado",
                data=pdf_file,
                file_name=result.pdf_path.name,
                mime="application/pdf",
            )


def render_search(engine, filters):
    if "offset" not in st.session_state:
        st.session_state.offset = 0
    if "last_search_key" not in st.session_state:
        st.session_state.last_search_key = None

    query, related_query, match_label, distance_label, year_filter, month_filter, sort_label = filters

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

    metric_cols = st.columns(3)
    metric_cols[0].metric("PDFs baixados", response.total_pdfs)
    metric_cols[1].metric("PDFs indexados", response.indexed_pdfs)
    metric_cols[2].metric("Falhas de indexacao", response.failed_pdfs)

    if response.year_counts:
        with st.expander("Contagem por ano/mes"):
            st.write("Anos:", response.year_counts)
            st.write("Meses:", response.month_counts)

    if not response.results:
        st.info("Nenhum resultado encontrado para os filtros atuais.")
        return

    table = pd.DataFrame(result_rows(response.results))
    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        height=min(620, 38 + (len(response.results) + 1) * 35),
        column_config={
            "Data": st.column_config.TextColumn("Data", width="small"),
            "Ano/Mes": st.column_config.TextColumn("Ano/Mes", width="small"),
            "Trecho": st.column_config.TextColumn("Trecho", width="large"),
            "Arquivo": st.column_config.TextColumn("Arquivo", width="medium"),
            "Caminho": st.column_config.TextColumn("Caminho", width="large"),
        },
    )

    render_download_picker(response.results)

    nav_cols = st.columns([1, 1, 6])
    if nav_cols[0].button("Anterior", disabled=response.offset == 0):
        st.session_state.offset = max(0, response.offset - PAGE_SIZE)
        st.rerun()
    if nav_cols[1].button("Proxima", disabled=not response.has_more):
        st.session_state.offset = response.offset + len(response.results)
        st.rerun()


def main():
    st.set_page_config(page_title="DJE Finder TJRR", layout="wide")
    st.title("DJE Finder TJRR")
    st.caption("Busca textual nos PDFs indexados localmente.")
    configure_data_dir(Config.BASE_DIR)

    filters_main = render_main_filters()
    with st.sidebar:
        filters_sidebar = render_sidebar_filters()

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
