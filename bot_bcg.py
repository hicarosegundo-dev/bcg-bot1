# bot_bcg_improved.py
import logging
import re
import gspread
import pdfplumber
import os
import time
import sqlite3
import html as html_lib
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)
from unidecode import unidecode

# tenta importar flashtext (opcional, acelera buscas com múltiplas keywords)
try:
    from flashtext import KeywordProcessor
    HAS_FLASHTEXT = True
except Exception:
    HAS_FLASHTEXT = False

# --- SUAS CHAVES DE TESTE (mantive conforme você enviou) ---
TOKEN = "8030056053:AAFvjsWFeQTPYnv8OAlj_6aeSl0D_7soqBg"
SPREADSHEET_ID = "1oF5YBiyOyO9NVo2pdx_xq7CJb4P3lLr9ia_BbUqS4YM"
# -----------------------------------------------------------

MAX_MESSAGE_LENGTH = 4096  # limite do Telegram
DELAY_BETWEEN_SENDS = 0.35  # segundos entre envios para evitar flood
DB_PATH = "notificacoes.db"

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversa cadastro
(PEDINDO_NOME, PEDINDO_MATRICULA) = range(2)

# dados carregados da planilha: chave = nome normalizado (sem acentos, lower)
usuarios_dados_completos = {}

# ----------------------------------------------------------
# Utilitários
# ----------------------------------------------------------
def normalize(s: str) -> str:
    """Remove acentos, normaliza espaços e coloca em lowercase."""
    return unidecode(str(s)).strip().lower()

def ensure_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS notificacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            chat_id TEXT,
            termo_encontrado TEXT,
            status TEXT,
            error TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    con.commit()
    con.close()

def log_notification(nome, chat_id, termo, status, error=None):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO notificacoes (nome, chat_id, termo_encontrado, status, error) VALUES (?, ?, ?, ?, ?)",
        (nome, str(chat_id), termo, status, error if error else None),
    )
    con.commit()
    con.close()

# ----------------------------------------------------------
# Planilha (Google Sheets)
# ----------------------------------------------------------
def carregar_usuarios_da_planilha():
    """Carrega os dados dos usuários da planilha Google Sheets para a memória."""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)
        
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        records = sheet.get_all_records()
        
        usuarios_dados_completos.clear()
        for record in records:
            # adapta caso os nomes das colunas variem um pouco
            raw_nome = record.get("Nome") or record.get("nome") or record.get("Nome Completo") or ""
            raw_id = record.get("ID Telegram") or record.get("id_telegram") or record.get("Chat ID") or record.get("ChatID")
            if not raw_nome or not raw_id:
                continue

            nome_completo_original = str(raw_nome).strip()
            nome_norm = normalize(nome_completo_original)
            id_telegram = str(raw_id).strip()
            pm = str(record.get("PM", "") or "").strip()
            matricula = str(record.get("Matrícula", "") or record.get("Matricula", "") or "").replace("-", "").replace(".", "").strip()

            usuarios_dados_completos[nome_norm] = {
                "id": id_telegram,
                "pm": pm,
                "nome_completo": nome_completo_original,
                "nome_norm": nome_norm,
                "matricula": matricula,
            }
        logger.info(f"Planilha carregada. {len(usuarios_dados_completos)} usuários cadastrados.")
    except Exception as e:
        logger.error(f"Erro ao carregar a planilha: {e}")

def adicionar_usuario_na_planilha(pm, nome, matricula, id_telegram):
    """Adiciona uma nova linha com os dados de um novo usuário na planilha."""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        
        row = [pm, nome, matricula, id_telegram]
        sheet.append_row(row)
        
        carregar_usuarios_da_planilha()
        logger.info(f"Novo usuário adicionado na planilha: {nome}")
        return True
    except Exception as e:
        logger.error(f"Erro ao adicionar usuário na planilha: {e}")
        return False

# ----------------------------------------------------------
# Busca: monta estrutura de busca (flashtext ou regex)
# ----------------------------------------------------------
def build_search_struct():
    """
    Cria estruturas de busca para todos os termos relevantes (PM, nome, matrícula).
    Retorna tipo: ("flash", kp, map_term_to_original) ou ("regex", [(pattern, original_term), ...])
    """
    termos = {}  # map termo_normalizado -> termo_original_exibicao (p.ex. nome completo)
    for nome_norm, info in usuarios_dados_completos.items():
        # adiciona nome
        termos[nome_norm] = info['nome_completo']
        # adiciona pm se existir
        pm = info.get("pm", "")
        if pm:
            termos[normalize(pm)] = info['nome_completo']
        # adiciona matricula se existir
        matricula = info.get("matricula", "")
        if matricula:
            termos[normalize(matricula)] = info['nome_completo']

    termos_list = list(termos.items())  # [(term_norm, nome_exibicao), ...]

    if HAS_FLASHTEXT and termos_list:
        kp = KeywordProcessor(case_sensitive=False)
        # flashtext expects keywords as they appear — we will add normalized variants
        for term_norm, display in termos_list:
            kp.add_keyword(term_norm)
        # map term_norm -> display name
        return ("flash", kp, dict(termos_list))
    else:
        patterns = []
        for term_norm, display in termos_list:
            # regex com boundary; term_norm já normalizado (sem acentos)
            pat = re.compile(r"\b" + re.escape(term_norm) + r"\b", flags=re.IGNORECASE)
            patterns.append((pat, display, term_norm))
        return ("regex", patterns, dict(termos_list))

# ----------------------------------------------------------
# Verificação e envio
# ----------------------------------------------------------
async def verificar_mensagens(update: Update, context: ContextTypes.DEFAULT_TYPE, texto_completo: str) -> None:
    """
    Verifica se algum usuário cadastrado é mencionado no texto (texto completo do PDF)
    e envia notificação com um trecho.
    """
    if not texto_completo or not texto_completo.strip():
        return

    # Pré-processa: gera versão normalizada do texto para busca
    # Para economia de memória em PDFs grandes, já processamos página-a-página em quem chama
    texto_norm = normalize(texto_completo)

    # tentativa de extrair título (heurística)
    titulo_completo = ""
    match = re.search(r"^(Boletim Interno nº .*|BCG nº .*)$", texto_completo, re.MULTILINE | re.IGNORECASE)
    if match:
        titulo_completo = match.group(0).strip()
    if not titulo_completo:
        linhas = texto_completo.strip().split('\n')
        if len(linhas) > 1:
            titulo_completo = linhas[1].strip()
    if not titulo_completo:
        titulo_completo = "Boletim"

    # Separa seções por padrão de data (mantém trechos para contexto)
    secoes = re.split(r'DIA \d{2} DE \w+ DE \d{4}', texto_completo, flags=re.IGNORECASE)
    # Também normaliza as secoes paralelamente para buscas rápidas
    secoes_norm = [normalize(s) for s in secoes]

    search_kind, search_struct, term_map = build_search_struct()

    encontrados_por_nome = {}  # map nome_exibicao -> list of (termo_encontrado, trecho)

    if search_kind == "flash":
        # usando flashtext: extrai keywords da versão normalizada
        matches = search_struct.extract_keywords(texto_norm)
        matches = list(dict.fromkeys(matches))  # dedupe mantendo ordem
        for matched in matches:
            display = term_map.get(matched, None)
            if not display:
                continue
            # procura trecho onde apareceu (busca em secoes_norm)
            trecho = None
            for sec_text, sec_norm in zip(secoes, secoes_norm):
                if re.search(r"\b" + re.escape(matched) + r"\b", sec_norm, flags=re.IGNORECASE):
                    trecho = sec_text.strip()
                    break
            if not trecho:
                # fallback: pega começo do documento
                trecho = texto_completo[:800]
            encontrados_por_nome.setdefault(display, []).append((matched, trecho))
    else:
        # regex path
        for pat, display, term_norm in search_struct:
            if pat.search(texto_norm):
                # encontra seção correspondente
                trecho = None
                for sec_text, sec_norm in zip(secoes, secoes_norm):
                    if pat.search(sec_norm):
                        trecho = sec_text.strip()
                        break
                if not trecho:
                    trecho = texto_completo[:800]
                encontrados_por_nome.setdefault(display, []).append((term_norm, trecho))

    # Monta e envia mensagens
    for nome_exibicao, ocorrencias in encontrados_por_nome.items():
        # pega user_id através do usuario_dados_completos: procura por nome_norm
        # Note: vários termos (pm/matricula) apontam pro mesmo nome_exibicao
        # buscamos a primeira entrada cujo nome_completo corresponde
        user_entry = None
        for info in usuarios_dados_completos.values():
            if info['nome_completo'] == nome_exibicao:
                user_entry = info
                break
        if not user_entry:
            continue
        chat_id = user_entry['id']

        # Junta ocorrências em um único trecho (limitando tamanho)
        # preferimos o primeiro trecho encontrado
        termo_encontrado, trecho = ocorrencias[0]
        # escolhe linhas ao redor da ocorrência para contexto
        trecho_lines = trecho.split('\n')
        # tenta achar a linha que contém o termo (na versão normalizada)
        trecho_norm = normalize(trecho)
        idx = None
        try:
            # busca índice aproximado
            for i, l in enumerate(trecho_lines):
                if re.search(re.escape(termo_encontrado), normalize(l), re.IGNORECASE):
                    idx = i
                    break
        except Exception:
            idx = None
        if idx is None:
            idx = 0
        start = max(0, idx - 5)
        end = min(len(trecho_lines), idx + 6)
        trecho_final = "\n".join(trecho_lines[start:end]).strip()

        # Prepara mensagem (uso de <pre> para preservar formatação)
        # Escapa HTML para segurança
        trecho_esc = html_lib.escape(trecho_final)
        titulo_esc = html_lib.escape(titulo_completo)
        nome_esc = html_lib.escape(nome_exibicao)

        mensagem_final = (
            f"Olá, {nome_esc}!\n\n"
            f"Você foi mencionado no {titulo_esc}\n\n"
