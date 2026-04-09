import re
import time
import unicodedata
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, unquote
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from utils.selenium_driver import desabilitar_js, habilitar_js

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'pt-BR,pt;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}
PADRAO_CNPJ_FORMATADO = r'\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b'
PADRAO_CNPJ_SEM_FORMATACAO = r'\b\d{14}\b'


# ──────────────────────────────────────────
# HELPERS GERAIS
# ──────────────────────────────────────────
def normalizar_texto(texto):
    texto = texto.lower().strip()
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]', '', texto)


def formatar_cnpj(cnpj):
    cnpj_numeros = re.sub(r'\D', '', cnpj)
    if len(cnpj_numeros) == 14:
        # rejeita bases diferentes de 0001
        if cnpj_numeros[8:12] != "0001":
            return ""
        return (
            f"{cnpj_numeros[:2]}.{cnpj_numeros[2:5]}."
            f"{cnpj_numeros[5:8]}/{cnpj_numeros[8:12]}-{cnpj_numeros[12:]}"
        )
    return cnpj


def extrair_cnpj_texto(texto):
    cnpjs = re.findall(PADRAO_CNPJ_FORMATADO, texto)
    if cnpjs:
        primeiro = cnpjs[0]
        # Ignora CNPJ "00.000.000/0000-00"
        if primeiro != "00.000.000/0000-00":
            # rejeita base diferente de 0001 (XX.XXX.XXX/BBBB-YY)
            base = primeiro[12:16]
            if base == "0001":
                return primeiro

    for cnpj in re.findall(PADRAO_CNPJ_SEM_FORMATACAO, texto):
        # Ignora sequências com todos os dígitos iguais (000..., 111..., etc.)
        if len(set(cnpj)) == 1:
            continue
        # Ignora explicitamente 00000000000000
        if cnpj == "00000000000000":
            continue
        # rejeita base diferente de 0001
        if cnpj[8:12] != "0001":
            continue
        fmt = formatar_cnpj(cnpj)
        if fmt:
            return fmt

    return ""


def extrair_url_real_google(href):
    if not href:
        return None
    if href.startswith("http") and "google.com" not in href:
        return href
    match = re.search(r'[?&]q=(https?://[^&]+)', href)
    if match:
        return unquote(match.group(1))
    return None


# ──────────────────────────────────────────
# VALIDAÇÕES DE LINK
# ──────────────────────────────────────────
def validar_link_site_alvo(href, sites_permitidos):
    if not href:
        return False
    urls_excluir = [
        "/login", "/cadastro", "/contato", "/sobre", "google.com"
    ]
    for excluir in urls_excluir:
        if excluir in href.lower():
            return False
    return any(site in href for site in sites_permitidos)

def link_corresponde_empresa(url, nome_empresa):
    nome_norm = normalizar_texto(nome_empresa)

    if re.search(r'cnpj\.biz/\d+', url):
        return True

    # Melhor validação para econodata
    if 'econodata.com.br' in url:
        # Aceita qualquer URL do econodata que contenha empresa/CNPJ
        if '/consulta-empresa/' in url or '/empresas/' in url or re.search(r'/\d{14}', url):
            return True
        # Para outras URLs do econodata, validação mais flexível
        palavras = [p for p in nome_norm.split() if len(p) > 2]
        if not palavras:
            return True
        url_norm = normalizar_texto(url)
        encontradas = sum(1 for p in palavras if p in url_norm)
        return (encontradas / len(palavras)) >= 0.3

    palavras = [p for p in nome_norm.split() if len(p) > 2]
    if not palavras:
        return True
    url_norm = normalizar_texto(url)
    encontradas = sum(1 for p in palavras if p in url_norm)
    return (encontradas / len(palavras)) >= 0.4

# ──────────────────────────────────────────
# EXTRAÇÃO DE CNPJ DO HTML
# ──────────────────────────────────────────
def extrair_cnpj_especifico(html, nome_empresa, debug=False):
    soup = BeautifulSoup(html, 'html.parser')

    # Prioridade 1: H1
    try:
        h1 = soup.find('h1')
        if h1:
            cnpj = extrair_cnpj_texto(h1.get_text())
            if cnpj:
                return (cnpj, f"✅ CNPJ via H1: {cnpj}") if debug else cnpj
    except Exception:
        pass

    # Prioridade 2: tags <b>, <strong>, <span>
    try:
        for tag in soup.find_all(['b', 'strong', 'span']):
            cnpj = extrair_cnpj_texto(tag.get_text(strip=True))
            if cnpj:
                return (cnpj, f"✅ CNPJ via <{tag.name}>: {cnpj}") if debug else cnpj
    except Exception:
        pass

    # Prioridade 3: texto formatado
    texto = soup.get_text()
    cnpjs = re.findall(PADRAO_CNPJ_FORMATADO, texto)
    if cnpjs:
        return (cnpjs[0], f"✅ CNPJ formatado: {cnpjs[0]}") if debug else cnpjs[0]

    # Prioridade 4: sem formatação
    for cnpj in re.findall(PADRAO_CNPJ_SEM_FORMATACAO, texto):
        if len(set(cnpj)) > 1:
            fmt = formatar_cnpj(cnpj)
            return (fmt, f"✅ CNPJ convertido: {fmt}") if debug else fmt

    return ("", "❌ Nenhum CNPJ encontrado na página") if debug else ""


# ──────────────────────────────────────────
# SCRAPING NO SITE DA EMPRESA
# ──────────────────────────────────────────
def scrape_cnpj_from_site(url, debug=False):
    import pandas as pd
    if not url or pd.isna(url):
        return ("", "❌ Site vazio") if debug else ""
    url = str(url).strip()
    if not url.startswith("http"):
        url = "http://" + url
    try:
        response = requests.get(url, headers=HEADERS, timeout=8)
        cnpj = extrair_cnpj_texto(response.text)
        if debug:
            return (cnpj, f"✅ Encontrado: {cnpj}") if cnpj else \
                   ("", f"⚠️ Site acessado ({response.status_code}), CNPJ não encontrado")
        return cnpj
    except Exception as e:
        return ("", f"❌ Erro: {str(e)[:60]}") if debug else ""


# ──────────────────────────────────────────
# ACESSO VIA SELENIUM (sem JS → com JS)
# ──────────────────────────────────────────
def acessar_pagina_selenium_cnpj(url, driver):
    """Tenta sem JS primeiro, depois com JS como fallback.

    Se a URL for do cnpj.biz no formato https://cnpj.biz/XXXXXXXXXXXXXX, o CNPJ é
    extraído diretamente da URL e retornado já formatado, sem depender do HTML.
    """

    # Se a URL for cnpj.biz/14_digitos, tenta extrair o CNPJ direto da URL
    if "cnpj.biz" in url:
        match = re.search(r"cnpj\.biz/(\d{14})", url)
        if match:
            cnpj_bruto = match.group(1)
            cnpj_formatado = formatar_cnpj(cnpj_bruto)
            if cnpj_formatado:
                return ("cnpj_direto", cnpj_formatado)

    # Tentativa 1: sem JS
    try:
        desabilitar_js(driver)
        driver.get(url)
        time.sleep(2)
        try:
            body = driver.find_element(By.TAG_NAME, "body").text
            cnpj = extrair_cnpj_texto(body)
            if cnpj:
                return ("cnpj_direto", cnpj)
        except Exception:
            pass
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        cnpj = extrair_cnpj_texto(soup.get_text())
        if cnpj:
            return ("cnpj_direto", cnpj)
    except Exception:
        pass
    finally:
        habilitar_js(driver)

    # Tentativa 2: com JS (não dependerá de HTML do cnpj.biz, pois já tentamos pela URL)
    try:
        driver.get(url)
        try:
            WebDriverWait(driver, 8).until(
                lambda d: re.search(
                    PADRAO_CNPJ_FORMATADO,
                    d.find_element(By.TAG_NAME, "body").text
                )
            )
        except Exception:
            time.sleep(4)
        cnpj = extrair_cnpj_texto(driver.find_element(By.TAG_NAME, "body").text)
        if cnpj:
            return ("cnpj_direto", cnpj)
        return ("html", driver.page_source)
    except Exception:
        return ("html", "")


# ──────────────────────────────────────────
# FALLBACK: DUCKDUCKGO VIA REQUESTS
# ──────────────────────────────────────────
def _buscar_links_duckduckgo(query, sites_permitidos, nome, debug_log, debug):
    """Busca no DuckDuckGo HTML (sem Selenium) e retorna lista de URLs válidas."""
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query, "kl": "br-pt"},
            headers={
                **HEADERS,
                "Referer": "https://duckduckgo.com/",
            },
            timeout=10,
        )
        soup = BeautifulSoup(resp.text, 'html.parser')
        links_encontrados = []

        ancoras = soup.select('a.result__a, a.result__url')
        if debug:
            debug_log.append(f"  [DDG] {len(ancoras)} âncoras encontradas na página")

        for a in ancoras:
            href = a.get('href', '')
            # DDG encapsula URLs em /l/?uddg=<URL-encoded> — captura o valor bruto e decodifica
            match = re.search(r'[?&]uddg=([^&]+)', href)
            if match:
                url_real = unquote(match.group(1))
            elif href.startswith('http'):
                url_real = href
            else:
                url_real = None

            if not url_real:
                continue

            if debug:
                debug_log.append(f"  [DDG RAW] {url_real[:90]}")

            if validar_link_site_alvo(url_real, sites_permitidos) and link_corresponde_empresa(url_real, nome):
                if url_real not in links_encontrados:
                    links_encontrados.append(url_real)
                    if debug:
                        debug_log.append(f"  ✅ [DDG] Link aceito: {url_real[:80]}")
                    if len(links_encontrados) >= 5:
                        break
            elif debug:
                debug_log.append(f"  ⛔ [DDG] Rejeitado: {url_real[:60]}")
        return links_encontrados
    except Exception as e:
        if debug:
            debug_log.append(f"❌ [DDG] Erro: {str(e)[:80]}")
        return []


# ──────────────────────────────────────────
# BUSCA NO GOOGLE (com fallback DuckDuckGo)
# ──────────────────────────────────────────
def buscar_cnpj_google(nome, driver, sites_permitidos, debug=False):
    debug_log = []
    try:
        query = nome + ' cnpj'
        habilitar_js(driver)
        driver.get(f"https://www.google.com/search?q={quote(query)}&hl=pt-BR")

        # Aguarda links reais de resultados (até 10s)
        try:
            WebDriverWait(driver, 10).until(
                lambda d: len(d.find_elements(By.CSS_SELECTOR, "a[href]")) > 5
            )
        except Exception:
            pass
        time.sleep(3)

        # ── Detecção de CAPTCHA / sorry page ──
        url_atual = driver.current_url
        google_bloqueou = (
            "/sorry/" in url_atual
            or "google.com/sorry" in url_atual
            or len(driver.find_elements(By.CSS_SELECTOR, "a")) <= 5
        )

        links_encontrados = []

        if google_bloqueou:
            if debug:
                debug_log.append(f"🚫 Google bloqueou (CAPTCHA). Usando DuckDuckGo como fallback.")
            links_encontrados = _buscar_links_duckduckgo(
                query, sites_permitidos, nome, debug_log, debug
            )
        else:
            links_elementos = driver.find_elements(By.CSS_SELECTOR, "a")
            if debug:
                debug_log.append(f"🔍 Google retornou {len(links_elementos)} elementos <a>")

            for elemento in links_elementos:
                try:
                    href = elemento.get_attribute("href")
                    url_real = extrair_url_real_google(href)
                    if url_real and validar_link_site_alvo(url_real, sites_permitidos):
                        if link_corresponde_empresa(url_real, nome):
                            if url_real not in links_encontrados:
                                links_encontrados.append(url_real)
                                if debug:
                                    debug_log.append(f"  ✅ Link aceito: {url_real[:80]}")
                                if len(links_encontrados) >= 5:
                                    break
                        elif debug:
                            debug_log.append(f"  ❌ Link rejeitado (empresa): {url_real[:80]}")
                    elif debug and url_real:
                        debug_log.append(f"  ⛔ Fora dos sites permitidos: {url_real[:80]}")
                except Exception:
                    continue

        if debug:
            debug_log.append(f"📊 Total de links válidos: {len(links_encontrados)}")

        if not links_encontrados:
            return ("", " | ".join(debug_log + ["❌ Nenhum link válido"])) if debug else ""

        # Regra específica para cnpj.biz SOMENTE quando ele é a única fonte selecionada:
        # - NÃO buscar mais dentro do HTML do cnpj.biz
        # - Pegar CNPJ direto da URL do link 1, depois link 2
        # - Se ainda assim não achar, retorna vazio (para a aba depois tentar pelo site)
        usar_regra_cnpjbiz = (
            len(sites_permitidos) == 1 and
            any("cnpj.biz" in site for site in sites_permitidos)
        )

        if usar_regra_cnpjbiz:
            # Tenta 1º e 2º links aceitos
            for idx in range(min(2, len(links_encontrados))):
                link = links_encontrados[idx]
                try:
                    # Caso 1: URL já contém os 14 dígitos — extrai diretamente
                    match = re.search(r"cnpj\.biz/(\d{14})", link)
                    if match:
                        cnpj_bruto = match.group(1)
                        cnpj_formatado = formatar_cnpj(cnpj_bruto)
                        if cnpj_formatado:
                            if debug:
                                debug_log.append(
                                    f"  Link {idx + 1}: ✅ CNPJ direto da URL: {cnpj_formatado}"
                                )
                            return (cnpj_formatado, " | ".join(debug_log)) if debug else cnpj_formatado

                    # Caso 2: URL do cnpj.biz sem 14 dígitos (ex: /cnpj/empresa-nome)
                    # — acessa a página via Selenium para obter o CNPJ ou a URL final (redirect)
                    if debug:
                        debug_log.append(
                            f"  Link {idx + 1}: ⚠️ URL sem 14 dígitos, acessando via Selenium: {link[:80]}"
                        )
                    tipo, conteudo = acessar_pagina_selenium_cnpj(link, driver)
                    if tipo == "cnpj_direto" and conteudo:
                        cnpj_formatado = conteudo
                        if debug:
                            debug_log.append(
                                f"  Link {idx + 1}: ✅ CNPJ via Selenium (fallback): {cnpj_formatado}"
                            )
                        return (cnpj_formatado, " | ".join(debug_log)) if debug else cnpj_formatado

                    # Tenta extrair da URL atual após redirect (o driver pode ter navegado)
                    try:
                        url_atual = driver.current_url
                        match2 = re.search(r"cnpj\.biz/(\d{14})", url_atual)
                        if match2:
                            cnpj_formatado = formatar_cnpj(match2.group(1))
                            if cnpj_formatado:
                                if debug:
                                    debug_log.append(
                                        f"  Link {idx + 1}: ✅ CNPJ via redirect URL: {cnpj_formatado}"
                                    )
                                return (cnpj_formatado, " | ".join(debug_log)) if debug else cnpj_formatado
                    except Exception:
                        pass

                    # Tenta extrair do HTML retornado
                    if tipo == "html" and conteudo:
                        cnpj_from_html = extrair_cnpj_texto(conteudo)
                        if cnpj_from_html:
                            if debug:
                                debug_log.append(
                                    f"  Link {idx + 1}: ✅ CNPJ via HTML cnpj.biz: {cnpj_from_html}"
                                )
                            return (cnpj_from_html, " | ".join(debug_log)) if debug else cnpj_from_html

                    if debug:
                        debug_log.append(f"  Link {idx + 1}: ❌ CNPJ não encontrado")

                except Exception as e:
                    if debug:
                        debug_log.append(
                            f"  Link {idx + 1}: Erro - {str(e)[:60]}"
                        )
                    continue

            if debug:
                debug_log.append("❌ Nenhum CNPJ obtido pelos 2 primeiros links do cnpj.biz")
            return ("", " | ".join(debug_log)) if debug else ""

        # Fluxo padrão (quando NÃO é só cnpj.biz): processa links normalmente
        for i, link in enumerate(links_encontrados, 1):
            try:
                time.sleep(1)
                tipo, conteudo = acessar_pagina_selenium_cnpj(link, driver)
                if tipo == "cnpj_direto":
                    cnpj = conteudo
                    if debug:
                        debug_log.append(f"  Link {i}: ✅ CNPJ direto: {cnpj}")
                else:
                    if debug:
                        cnpj, log = extrair_cnpj_especifico(conteudo, nome, debug=True)
                        debug_log.append(f"  Link {i}: {log}")
                    else:
                        cnpj = extrair_cnpj_especifico(conteudo, nome)
                if cnpj:
                    if debug:
                        debug_log.append(f"✅ CNPJ ENCONTRADO: {cnpj}")
                    return (cnpj, " | ".join(debug_log)) if debug else cnpj
            except Exception as e:
                if debug:
                    debug_log.append(f"  Link {i}: Erro - {str(e)[:60]}")
                continue

        return ("", " | ".join(debug_log + ["❌ Sem CNPJ em nenhum link"])) if debug else ""
    except Exception as e:
        return ("", f"❌ Erro geral: {str(e)[:60]}") if debug else ""
