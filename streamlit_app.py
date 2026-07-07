from pathlib import Path

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
    "Relevância": SORT_RELEVANCE,
    "Mais recentes": SORT_NEWEST,
    "Mais antigos": SORT_OLDEST,
}
MATCH_OPTIONS = {
    "Todos os termos": MATCH_ALL_TERMS,
    "Frase exata": MATCH_EXACT_PHRASE,
    "Contexto próximo": MATCH_NEAR_CONTEXT,
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


def result_card(result):
    with st.container(border=True):
        st.caption(f"{result.display_date} • {result.year}/{result.month}")
        st.markdown(result.snippet.replace("[", "**").replace("]", "**"))
        st.code(str(result.pdf_path), language=None)

        cols = st.columns([1, 5])
        if result.pdf_path.is_file():
            with result.pdf_path.open("rb") as pdf_file:
                cols[0].download_button(
                    "Baixar PDF",
                    data=pdf_file,
                    file_name=result.pdf_path.name,
                    mime="application/pdf",
                    key=f"download-{result.date_str}-{result.pdf_path.name}",
                )
        else:
            cols[0].button("PDF ausente", disabled=True, key=f"missing-{result.date_str}")


def render_search(engine):
    if "offset" not in st.session_state:
        st.session_state.offset = 0
    if "last_search_key" not in st.session_state:
        st.session_state.last_search_key = None

    query = st.text_input("Termo principal", placeholder="Ex.: melquizedeque lima pereira")
    related_query = st.text_input("Perto de", placeholder="Ex.: elogiar")

    cols = st.columns([1, 1, 1, 1])
    year_filter = cols[0].text_input("Ano", placeholder="Todos")
    month_filter = cols[1].text_input("Mês", placeholder="Todos")
    match_label = cols[2].selectbox("Modo", list(MATCH_OPTIONS.keys()), index=0)
    sort_label = cols[3].selectbox("Ordenar", list(SORT_OPTIONS.keys()), index=0)

    distance_label = st.select_slider(
        "Distância do contexto",
        options=list(DISTANCE_OPTIONS.keys()),
        value="50 palavras",
        help="Usada quando o campo 'Perto de' está preenchido ou o modo é Contexto próximo.",
    )

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
        st.info("Digite um termo principal para iniciar a busca.")
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

    total_label = f"{response.total} resultado(s)"
    if response.total:
        current_end = response.offset + len(response.results)
        total_label = f"Exibindo {response.offset + 1}-{current_end} de {response.total} resultado(s)"
    st.subheader(total_label)

    if response.has_pending_indexing:
        pending = response.total_pdfs - response.indexed_pdfs
        st.warning(
            f"Ainda existem {pending} PDF(s) pendente(s) de indexação. "
            "A busca pode não cobrir toda a base."
        )

    metric_cols = st.columns(3)
    metric_cols[0].metric("PDFs baixados", response.total_pdfs)
    metric_cols[1].metric("PDFs indexados", response.indexed_pdfs)
    metric_cols[2].metric("Falhas de indexação", response.failed_pdfs)

    if response.year_counts:
        with st.expander("Contagem por ano/mês"):
            st.write("Anos:", response.year_counts)
            st.write("Meses:", response.month_counts)

    if not response.results:
        st.info("Nenhum resultado encontrado para os filtros atuais.")
        return

    for result in response.results:
        result_card(result)

    nav_cols = st.columns([1, 1, 6])
    if nav_cols[0].button("Anterior", disabled=response.offset == 0):
        st.session_state.offset = max(0, response.offset - PAGE_SIZE)
        st.rerun()
    if nav_cols[1].button("Próxima", disabled=not response.has_more):
        st.session_state.offset = response.offset + len(response.results)
        st.rerun()


def main():
    st.set_page_config(page_title="DJE Finder TJRR", layout="wide")
    st.title("DJE Finder TJRR")
    st.caption("Busca textual nos PDFs indexados localmente.")

    with st.sidebar:
        st.header("Base local")
        data_dir = st.text_input("Diretório de dados", value=str(Config.BASE_DIR))
        configure_data_dir(data_dir)
        st.code(str(Config.DB_FILE), language=None)

        if db_exists():
            st.success("Banco SQLite encontrado.")
        else:
            st.error("Banco SQLite não encontrado.")
            st.info(
                "Execute a sincronização/indexação pelo app desktop ou aponte para "
                "um diretório que contenha `dje_finder.db`."
            )

        st.divider()
        st.markdown(
            "No Streamlit Community Cloud, os dados precisam estar disponíveis no "
            "ambiente publicado ou em um armazenamento externo configurado."
        )

    if not db_exists():
        return

    render_search(PDFSearchEngine(page_size=PAGE_SIZE))


if __name__ == "__main__":
    main()
