import re
import time
from urllib.parse import quote

from selenium.webdriver.common.by import By

from utils.selenium_driver import habilitar_js
from utils.cnpj_utils import normalizar_texto, extrair_url_real_google

DOMINIOS_IGNORAR = [
    "google.com", "facebook.com", "instagram.com", "linkedin.com",
    "youtube.com", "twitter.com", "wikipedia.org", "econodata.com.br",
    "cnpj.biz", "receita.fazenda.gov.br", "jusbrasil.com.br",
    "tiktok.com", "whatsapp.com", "maps.google", "glassdoor.com",
    "indeed.com", "reclameaqui.com.br", "tripadvisor.com"
]


def dominio_ignorado(url):
    return any(d in url for d in DOMINIOS_IGNORAR)


def extrair_dominio_raiz(url):
    match = re.search(r'https?://(?:www\.)?([^/]+)', url)
    return match.group(1) if match else url


def buscar_site_empresa(nome, driver, debug=False):
    """Busca o site oficial da empresa no Google."""
    debug_log = []
    try:
        habilitar_js(driver)
        query = f'"{nome}" site oficial'
        driver.get(f"https://www.google.com/search?q={quote(query)}&hl=pt-BR")
        time.sleep(3)

        links_elementos = driver.find_elements(By.CSS_SELECTOR, "a")
        if debug:
            debug_log.append(f"🔍 Google retornou {len(links_elementos)} elementos <a>")

        for elemento in links_elementos:
            try:
                href = elemento.get_attribute("href")
                if not href:
                    continue
                url_real = extrair_url_real_google(href)
                if not url_real or not url_real.startswith("http"):
                    continue
                if dominio_ignorado(url_real):
                    if debug:
                        debug_log.append(f"  ❌ Ignorado (domínio bloqueado): {url_real[:80]}")
                    continue

                nome_norm = normalizar_texto(nome)
                dominio = normalizar_texto(extrair_dominio_raiz(url_real))
                palavras = [p for p in nome_norm.split() if len(p) > 3]

                if palavras:
                    encontradas = sum(1 for p in palavras if p in dominio)
                    if (encontradas / len(palavras)) < 0.3:
                        if debug:
                            debug_log.append(f"  ❌ Ignorado (nome não bate): {url_real[:80]}")
                        continue

                dominio_final = f"https://www.{extrair_dominio_raiz(url_real)}"
                if debug:
                    debug_log.append(f"  ✅ Site encontrado: {dominio_final}")
                return (dominio_final, " | ".join(debug_log)) if debug else dominio_final

            except Exception:
                continue

        return ("", " | ".join(debug_log + ["❌ Nenhum site encontrado"])) if debug else ""
    except Exception as e:
        return ("", f"❌ Erro geral: {str(e)[:60]}") if debug else ""
