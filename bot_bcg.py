import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext, Application
import pandas as pd

# Configurações do logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Função de start do bot
def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Olá! Eu sou o bot BCG.")

# Função de comando help
def help_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Comandos disponíveis:\n/start - Iniciar o bot\n/help - Comandos de ajuda")

# Função para carregar os dados da planilha
def carregar_planilha():
    try:
        # Supondo que 'credentials.json' seja a planilha que você usa
        df = pd.read_excel('credenciais.xlsx')
        logger.info("Planilha carregada. {} usuários cadastrados.".format(len(df)))
    except Exception as e:
        logger.error(f"Erro ao carregar a planilha: {e}")

# Função principal que inicializa o bot
def main():
    # Carregar a planilha ao iniciar
    carregar_planilha()

    # Iniciar o aplicativo com o Token do bot
    token = '8030056053:AAFvjsWFeQTPYnv8OAlj_6aeSl0D_7soqBg'  # Coloque seu token do Telegram aqui
    application = Application.builder().token(token).build()

    # Adicionar os comandos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    # Iniciar o bot
    logger.info("O bot BCG está rodando. Pressione Ctrl+C para parar.")
    application.run_polling()  # Sem a necessidade de passar 'port'

if __name__ == '__main__':
    main()
