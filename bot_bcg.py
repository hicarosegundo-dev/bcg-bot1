import logging
import re
import gspread
import pdfplumber
import os
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

# --- Usando variáveis de ambiente --- 
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')  # Agora o token vem da variável de ambiente
GOOGLE_CREDENTIALS = os.getenv('GOOGLE_CREDENTIALS')  # Credenciais do Google
SPREADSHEET_ID = "1oF5YBiyOyO9NVo2pdx_xq7CJb4P3lLr9ia_BbUqS4YM"
# ------------------------------------

MAX_MESSAGE_LENGTH = 4096

# Configuração de logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

(PEDINDO_NOME, PEDINDO_MATRICULA) = range(2)

usuarios_dados_completos = {}

def carregar_usuarios_da_planilha():
    """Carrega os dados dos usuários da planilha Google Sheets para a memória."""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(eval(GOOGLE_CREDENTIALS), scope)  # Usando a variável de ambiente
        client = gspread.authorize(creds)
        
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        records = sheet.get_all_records()
        
        usuarios_dados_completos.clear()
        for record in records:
            if "Nome" in record and "ID Telegram" in record:
                nome_completo_original = str(record.get("Nome", "")).strip().upper()
                id_telegram = record.get("ID Telegram")
                
                if not nome_completo_original or not id_telegram:
                    continue

                usuarios_dados_completos[nome_completo_original] = {
                    "id": str(id_telegram).strip(),
                    "pm": str(record.get("PM", "")).strip(),
                    "nome_completo": nome_completo_original,
                    "matricula": str(record.get("Matrícula", "")).replace("-", "").replace(".", "").strip(),
                }
        logger.info(f"Planilha carregada. {len(usuarios_dados_completos)} usuários cadastrados.")
    except Exception as e:
        logger.error(f"Erro ao carregar a planilha: {e}")

def adicionar_usuario_na_planilha(pm, nome, matricula, id_telegram):
    """Adiciona uma nova linha com os dados de um novo usuário na planilha."""
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(eval(GOOGLE_CREDENTIALS), scope)  # Usando a variável de ambiente
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

async def start_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Inicia o processo de cadastro pedindo o nome completo."""
    await update.message.reply_text(
        "Olá! Para te cadastrar, preciso de algumas informações.\n"
        "Qual o seu nome completo?",
        reply_markup=ReplyKeyboardMarkup([['/cancelar']], one_time_keyboard=True, resize_keyboard=True)
    )
    return PEDINDO_NOME

async def pedir_matricula(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Armazena o nome completo e pede a matrícula."""
    full_name = update.message.text
    context.user_data['full_name'] = full_name
    await update.message.reply_text(
        "Entendido. Agora, por favor, informe a sua matrícula funcional.",
        reply_markup=ReplyKeyboardRemove()
    )
    return PEDINDO_MATRICULA

async def finalizar_cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Finaliza o cadastro, salva os dados e encerra a conversa."""
    matricula = update.message.text
    
    nome = context.user_data.get('full_name').upper().strip()
    matricula_limpa = matricula.replace("-", "").replace(".", "").strip()
    id_telegram = update.message.from_user.id
    
    if adicionar_usuario_na_planilha("", nome, matricula_limpa, id_telegram):
        await update.message.reply_text(
            f"Cadastro concluído com sucesso, {nome}!\n"
            f"Matrícula: {matricula_limpa}\n\n"
            f"Este Bot tem a finalidade de lhe avisar quando algo for publicado em seu nome no BCG."
        )
    else:
        await update.message.reply_text(
            "Ocorreu um erro ao salvar seus dados. Por favor, tente novamente mais tarde."
        )

    context.user_data.clear()
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela o processo de cadastro."""
    await update.message.reply_text(
        "Cadastro cancelado.",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia uma mensagem de boas-vindas com o menu principal."""
    keyboard = [['Cadastrar']]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
        "Olá! Eu sou o Bot BCG. Clique em 'Cadastrar' para iniciar.",
        reply_markup=reply_markup
    )

async def verificar_mensagens(update: Update, context: ContextTypes.DEFAULT_TYPE, texto_completo: str) -> None:
    """Verifica se algum usuário cadastrado é mencionado no texto e envia a notificação."""
    
    nomes_encontrados_com_detalhes = {}
    
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

    secoes = re.split(r'DIA \d{2} DE \w+ DE \d{4}', texto_completo, flags=re.IGNORECASE)
    
    for nome_completo_original, detalhes_usuario in usuarios_dados_completos.items():
        pm_numero = detalhes_usuario.get("pm", "") 
        nome_completo = detalhes_usuario["nome_completo"]
        matricula_limpa = detalhes_usuario["matricula"]
        user_id = detalhes_usuario["id"]

        termos_de_busca = [
            re.escape(pm_numero),
            re.escape(nome_completo),
            re.escape(matricula_limpa)
        ]

        termo_encontrado = None
        for termo in termos_de_busca:
            if termo: 
                regex_busca = r'\b' + termo + r'\b'
                if re.search(regex_busca, texto_completo, re.IGNORECASE):
                    termo_encontrado = termo
                    break
        
        if termo_encontrado:
            for secao in secoes:
                if re.search(regex_busca, secao, re.IGNORECASE):
                    trecho_completo_da_citacao = secao.strip()
                    
                    trecho_linhas = trecho_completo_da_citacao.split('\n')
                    try:
                        indice_linha_citacao = next(i for i, linha in enumerate(trecho_linhas) if re.search(regex_busca, linha, re.IGNORECASE))
                        start_index = max(0, indice_linha_citacao - 5)
                        end_index = min(len(trecho_linhas), indice_linha_citacao + 6)
                        trecho_final = "\n".join(trecho_linhas[start_index:end_index]).strip()
                    except (ValueError, StopIteration):
                        trecho_final = trecho_completo_da_citacao

                    mensagem_final = (
                        f"Olá, {nome_completo}!\n\n"
                        f"Você foi mencionado no {titulo_completo}\n\n"
                        f"Trecho completo da citação:\n"
                        f"```\n{trecho_final}\n```\n\n"
                        f"Confira a publicação na íntegra acessando: https://sisbol.pm.ce.gov.br/login_bcg/"
                    )

                    if len(mensagem_final) > MAX_MESSAGE_LENGTH:
                        corte = len(mensagem_final) - MAX_MESSAGE_LENGTH + 5
                        trecho_final = trecho_final[:-corte] + "..."
                        mensagem_final = (
                            f"Olá, {nome_completo}!\n\n"
                            f"Você foi mencionado no {titulo_completo}\n\n"
                            f"Trecho completo da citação:\n"
                            f"```\n{trecho_final}\n```\n\n"
                            f"Confira a publicação na íntegra acessando: https://sisbol.pm.ce.gov.br/login_bcg/"
                        )

                    nomes_encontrados_com_detalhes[nome_completo] = {
                        "user_id": user_id,
                        "mensagem_final": mensagem_final
                    }
                    break

    for nome, detalhes in nomes_encontrados_com_detalhes.items():
        try:
            await context.bot.send_message(chat_id=detalhes['user_id'], text=detalhes['mensagem_final'])
            logger.info(f"Notificação enviada para {nome} (ID: {detalhes['user_id']})")
        except Exception as e:
            logger.error(f"Não foi possível enviar a mensagem para {nome}: {e}")
            
    if nomes_encontrados_com_detalhes:
        nomes_str = ", ".join(nomes_encontrados_com_detalhes.keys())
        resposta_grupo = f"Notificações enviadas para: {nomes_str}."
        await update.message.reply_text(resposta_grupo)

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa um arquivo PDF recebido."""
    await update.message.reply_text("Recebi o arquivo. Por favor, aguarde enquanto eu o analiso...")

    try:
        pdf_file = await context.bot.get_file(update.message.document.file_id)
        file_path = f"temp_pdf_{update.message.document.file_id}.pdf"
        await pdf_file.download_to_drive(file_path)

        texto_completo = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                texto_completo += page.extract_text() or ""
        
        os.remove(file_path)

        if texto_completo:
            await verificar_mensagens(update, context, texto_completo=texto_completo)
        else:
            await update.message.reply_text("Não foi possível extrair texto do PDF. O arquivo pode estar corrompido ou ser uma imagem.")

    except Exception as e:
        logger.error(f"Erro ao processar PDF: {e}")
        await update.message.reply_text("Ocorreu um erro ao processar o arquivo PDF.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa mensagens de texto genéricas como conteúdo de boletim."""
    if not update.message.text:
        return
    await verificar_mensagens(update, context, texto_completo=update.message.text)

def main() -> None:
    """Inicia o bot e configura os handlers na ordem correta."""
    carregar_usuarios_da_planilha()
    
    application = Application.builder().token(TOKEN).connect_timeout(30).read_timeout(30).build()
    
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Cadastrar$'), start_cadastro)],
        states={
            PEDINDO_NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, pedir_matricula)],
            PEDINDO_MATRICULA: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalizar_cadastro)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Regex('(?i)^(oi|olá|ola|bom dia|boa tarde|boa noite)$'), start))
    application.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_pdf))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("O bot BCG está rodando. Pressione Ctrl+C para parar.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
