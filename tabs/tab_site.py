import streamlit as st
import pandas as pd
import io
import time

from utils.selenium_driver import criar_selenium_driver
from utils.site_utils import buscar_site_empresa


def render_tab_site():
    st.markdown("Faça o upload de uma planilha Excel. A coluna A deve conter o **Nome da Empresa**.")
    st.markdown("O sistema buscará o site oficial de cada empresa no Google.")

    arquivo = st.file_uploader("Suba seu arquivo Excel (.xlsx)", type=["xlsx"], key="upload_site")
    modo_debug = st.checkbox("🐛 Debug", value=False, key="debug_site")

    if arquivo is not None:
        if st.button("▶️ Processar Sites", key="btn_site"):
            df = pd.read_excel(arquivo)
            if len(df.columns) < 1:
                st.error("O arquivo precisa ter pelo menos 1 coluna: A (Nome da Empresa).")
                return

            with st.spinner("Inicializando navegador..."):
                driver = criar_selenium_driver()

            sites_resultado = []
            logs_debug = [] if modo_debug else None
            total = len(df)
            barra = st.progress(0)
            status = st.empty()

            try:
                for index, row in df.iterrows():
                    status.text(f"Processando linha {index + 1} de {total}...")
                    nome = str(row.iloc[0]).strip()
                    site = ""
                    log = ""

                    if nome and nome.lower() != "nan":
                        time.sleep(2)
                        if modo_debug:
                            site, log = buscar_site_empresa(nome, driver, debug=True)
                        else:
                            site = buscar_site_empresa(nome, driver)

                    sites_resultado.append(site)
                    if modo_debug:
                        logs_debug.append(log)
                    barra.progress((index + 1) / total)
            finally:
                try:
                    driver.quit()
                except Exception:
                    pass

            df['Site Encontrado'] = sites_resultado
            if modo_debug:
                df['Log Debug'] = logs_debug

            status.text("✅ Processamento concluído!")
            encontrados = sum(1 for s in sites_resultado if s)
            st.success(f"Encontrados {encontrados} sites de {total} empresas.")
            st.dataframe(df, use_container_width=True)

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Resultados')
            output.seek(0)
            st.download_button(
                "📥 Baixar Resultados",
                data=output,
                file_name="resultados_sites.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
