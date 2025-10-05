import logging
from telegram.ext import Application, CommandHandler
import os
import json

# Configuração de log para depuração
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Função que será chamada quando o comando /start for enviado
async def start(update, context):
    await update.message.reply_text('Olá! Eu sou o seu bot.')

def main():
    # Tente carregar o arquivo de credenciais
    try:
        credentials_path = 'credentials.json'  # Caminho para o arquivo de credenciais
        # Aqui você pode adicionar a lógica para ler e carregar a planilha ou fazer outra operação
        with open(credentials_path, 'r') as file:
            credentials = json.load(file)
            logger.info("Planilha carregada com sucesso.")
            # Aqui você pode adicionar qualquer lógica adicional que precise com os dados do arquivo
    except FileNotFoundError:
        logger.error(f"Erro ao carregar a planilha: Arquivo {credentials_path} não encontrado.")
        return
    except json.JSONDecodeError:
        logger.error("Erro ao decodificar o arquivo JSON.")
        return

    # Inicializa o bot com o token
    application = Application.builder().token('8030056053:AAFvjsWFeQTPYnv8OAlj_6aeSl0D_7soqBg').build()

    # Adiciona o comando /start
    application.add_handler(CommandHandler("start", start))

    # Inicia o bot
    logger.info("O bot está rodando.")
    application.run_polling()

if __name__ == '__main__':
    main()
