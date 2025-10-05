import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os

# Habilitando logs para depuração
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Função de comando para /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('Olá! Eu sou o Bot.')

# Função principal para rodar o bot
async def main():
    # Adicione o token do seu bot aqui
    token = 'SEU_TOKEN_DO_BOT'
    app = Application.builder().token(token).build()

    # Registrando o comando /start
    app.add_handler(CommandHandler("start", start))

    # Rodando o bot
    logging.info("O bot está rodando... Pressione Ctrl+C para parar.")
    await app.run_polling()

if __name__ == '__main__':
    import sys
    from os import environ

    # Certifique-se de que o bot vai rodar na porta correta no Render
    port = int(environ.get("PORT", 5000))  # Usando a variável de ambiente PORT, com valor padrão 5000
    logger.info(f"Usando a porta {port} para a execução")

    # Rodando o bot
    from aiohttp import web
    app = web.Application()

    # Inicializando o bot na porta especificada
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    web.run_app(app, host="0.0.0.0", port=port)
