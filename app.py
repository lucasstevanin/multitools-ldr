import streamlit as st
from tabs.tab_cnpj import render_tab_cnpj
from tabs.tab_site import render_tab_site

st.set_page_config(page_title="Multitools LDR", layout="wide")
st.title("🛠️ Multitools LDR")

st.sidebar.info("""
**🛠️ Multitools LDR**

**Aba 1 — Localizador de CNPJ:**
- Coluna A: Nome | Coluna B: Site
- Busca no site da empresa e no Google

**Aba 2 — Localizador de Site:**
- Coluna A: Nome da Empresa
- Busca o site oficial no Google

Ative o modo **Debug** para ver logs detalhados.
""")

aba_cnpj, aba_site = st.tabs(["🏢 Localizador de CNPJ", "🌐 Localizador de Site"])

with aba_cnpj:
    render_tab_cnpj()

with aba_site:
    render_tab_site()