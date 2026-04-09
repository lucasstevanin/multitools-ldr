import streamlit as st
import pandas as pd
import io
import time

from utils.selenium_driver import criar_selenium_driver
from utils.cnpj_utils import scrape_cnpj_from_site, buscar_cnpj_google


def render_tab_cnpj():
    st.markdown("Faça o upload de uma planilha Excel. A coluna A deve conter o **Nome da Empresa** e a coluna B o **Site**.")
    st.markdown("O sistema buscará primeiro no site da empresa. Se não encontrar, buscará nos sites selecionados abaixo.")

    arquivo = st.file_uploader("Suba seu arquivo Excel (.xlsx)", type=["xlsx"], key="upload_cnpj")

    st.markdown("### 🔍 Selecione onde buscar os CNPJs:")
    col1, col2, col3 = st.columns(3)
    with col1:
        buscar_econodata = st.checkbox("📊 Econodata", value=True)
    with col2:
        buscar_cnpjbiz = st.checkbox("🔍 CNPJ.biz", value=True)
    with col3:
        modo_debug = st.checkbox("🐛 Debug", value=False, key="debug_cnpj")

    if arquivo is not None:
        if not buscar_econodata and not buscar_cnpjbiz:
            st.error("⚠️ Selecione pelo menos uma fonte de busca!")
            return

        sites_permitidos = []
        if buscar_econodata:
            sites_permitidos.append("econodata.com.br")
        if buscar_cnpjbiz:
            sites_permitidos.append("cnpj.biz")

        st.info(f"🎯 Buscando em: {', '.join(sites_permitidos)}")

        if st.button("▶️ Processar CNPJs", key="btn_cnpj"):
            df = pd.read_excel(arquivo)
            if len(df.columns) < 2:
                st.error("O arquivo precisa ter pelo menos 2 colunas: A (Nome) e B (Site).")
                return

            with st.spinner("Inicializando navegador..."):
                driver = criar_selenium_driver()

            cnpjs_resultado = []
            logs_debug = [] if modo_debug else None
            total = len(df)
            barra = st.progress(0)
            status = st.empty()

            try:
                for index, row in df.iterrows():
                    status.text(f"Processando linha {index + 1} de {total}...")
                    nome = row.iloc[0]
                    site = row.iloc[1]
                    cnpj = ""
                    log = ""

                    # Passo 1: Scraping no site da empresa
                    if pd.notna(site) and str(site).strip():
                        if modo_debug:
                            cnpj, log_site = scrape_cnpj_from_site(site, debug=True)
                            log = f"SITE: {log_site}"
                        else:
                            cnpj = scrape_cnpj_from_site(site)

                    # Passo 2: Google → Econodata/CNPJ.biz
                    if not cnpj and pd.notna(nome) and str(nome).strip():
                        time.sleep(3)
                        if modo_debug:
                            cnpj, log_google = buscar_cnpj_google(
                                str(nome).strip(), driver, sites_permitidos, debug=True
                            )
                            log += f" | GOOGLE: {log_google}"
                        else:
                            cnpj = buscar_cnpj_google(str(nome).strip(), driver, sites_permitidos)

                    cnpjs_resultado.append(cnpj)
                    if modo_debug:
                        logs_debug.append(log)
                    barra.progress((index + 1) / total)
            finally:
                try:
                    driver.quit()
                except Exception:
                    pass

            df['CNPJ Encontrado'] = cnpjs_resultado
            if modo_debug:
                df['Log Debug'] = logs_debug

            status.text("✅ Processamento concluído!")
            encontrados = sum(1 for c in cnpjs_resultado if c)
            st.success(f"Encontrados {encontrados} CNPJs de {total} empresas.")
            st.dataframe(df, use_container_width=True)

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Resultados')
            output.seek(0)
            st.download_button(
                "📥 Baixar Resultados",
                data=output,
                file_name="resultados_cnpjs.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
