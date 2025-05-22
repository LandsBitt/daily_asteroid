
import requests
import random
from datetime import datetime, time, timezone, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from deep_translator import GoogleTranslator
from dotenv import load_dotenv
from supabase import create_client, Client
import os
import logging





# Configura logging apenas para erros
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.ERROR
)
logger = logging.getLogger(__name__)

# Desativa logs de httpx, telegram.ext e apscheduler
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

# Carrega variáveis de ambiente
load_dotenv()
API_KEY = os.getenv("NASA_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Verifica se as variáveis de ambiente estão carregadas
if not API_KEY or not TELEGRAM_TOKEN:
    logger.error("NASA_API_KEY ou TELEGRAM_TOKEN não encontrados no .env")
    exit()

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("SUPABASE_URL ou SUPABASE_KEY não encontrados no .env")
    exit()
    
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)



# Adiciona um chat_id ao banco

def add_subscriber(chat_id):
    try:
        supabase.table("subscribers").insert({"chat_id": chat_id}).execute()
    except Exception as e:
        logger.error(f"Erro ao adicionar inscrito: {e}")


# Remove um chat_id do banco
def remove_subscriber(chat_id):
    try:
        supabase.table("subscribers").delete().eq("chat_id", chat_id).execute()
    except Exception as e:
        logger.error(f"Erro ao remover inscrito: {e}")

# Lista todos os chat_ids inscritos
def get_subscribers():
    try:
        response = supabase.table("subscribers").select("chat_id").execute()
        return [row["chat_id"] for row in response.data]
    except Exception as e:
        logger.error(f"Erro ao buscar inscritos: {e}")
        return []
    
# Função para traduzir texto
def traduzir(texto):
    try:
        return GoogleTranslator(source='en', target='pt').translate(texto)
    except Exception as e:
        logger.error(f"Erro na tradução: {e}")
        return texto

# Busca uma imagem aleatória do espaço
def imagem_espacial_aleatoria():
    try:
        query = random.choice(["galaxy", "nebula", "saturn", "jupiter", "apollo", "earth", "star", "sun", "planet", "asteroid", "space"])
        url = f"https://images-api.nasa.gov/search?q={query}&media_type=image"
        res = requests.get(url)
        if res.status_code != 200:
            logger.error(f"Erro na API da NASA (imagens): {res.status_code}")
            return None
        data = res.json()
        items = data.get("collection", {}).get("items", [])
        if not items:
            return None
        imagem = random.choice(items)
        return imagem["links"][0]["href"]
    except Exception as e:
        logger.error(f"Erro ao buscar imagem: {e}")
        return None

# Busca e formata a mensagem do asteroide
def get_asteroid_message():
    try:
        hoje = datetime.now().strftime("%Y-%m-%d")
        url = f"https://api.nasa.gov/neo/rest/v1/feed?start_date={hoje}&end_date={hoje}&api_key={API_KEY}"
        res = requests.get(url)
        
        if res.status_code != 200:
            logger.error(f"Erro na API da NASA (asteroides): {res.status_code}")
            return "Erro ao buscar dados da NASA."
        
        data = res.json()
        asteroides = data["near_earth_objects"].get(hoje, [])
        if not asteroides:
            return "Nenhum asteroide próximo hoje 😴"
        
        asteroide = random.choice(asteroides)
        nome = asteroide["name"]
        velocidade = float(asteroide["close_approach_data"][0]["relative_velocity"]["kilometers_per_hour"])
        distancia = float(asteroide["close_approach_data"][0]["miss_distance"]["kilometers"])
        
        msg_original = (
            f"🌍 Asteroide próximo da Terra! 🌠\n\n"
            f"Nome: {nome}\n"
            f"Distância aproximada: {int(distancia):,} km\n"
            f"Velocidade: {int(velocidade):,} km/h\n\n"
        )
        return traduzir(msg_original)
    except Exception as e:
        logger.error(f"Erro ao buscar dados do asteroide: {e}")
        return "Erro ao processar dados do asteroide."

# Envia mensagem ou foto para o Telegram
async def send_message(chat_id, text, imagem=None, context=None):
    if not context:
        logger.error("Contexto não fornecido para send_message")
        return
    try:
        if imagem:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=imagem,
                caption=f"{text}\n\n*Nota:* A imagem enviada NÃO tem relação direta com o asteroide, é só uma foto aleatória do espaço."
            )
        else:
            await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem para chat_id {chat_id}: {e}")

# Handler do comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # Adiciona o chat_id ao banco
    add_subscriber(chat_id)
    
    # Verifica se job_queue está disponível
    if context.job_queue is None:
        logger.error("JobQueue não está disponível. Instale python-telegram-bot[job-queue]")
        await update.message.reply_text("Erro: JobQueue não configurado. Contate o administrador.")
        return
    
    # Gera e envia a mensagem do asteroide
    mensagem = get_asteroid_message()
    imagem = imagem_espacial_aleatoria()
    await send_message(chat_id, mensagem, imagem, context)
    
    # Responde ao usuário
    await update.message.reply_text("Bot iniciado! Você receberá atualizações sobre asteroides diariamente às 10h (horário de Brasília).")
    
    # Agenda o envio diário para este chat
    context.job_queue.run_daily(
        callback=send_periodic_message,
        time=time(hour=10, minute=00, tzinfo=timezone(timedelta(hours=-3))),
        data=chat_id,
        name=str(chat_id)
    )

# Handler do comando /stop
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in get_subscribers():
        remove_subscriber(chat_id)
        # Remove o job de envio diário
        current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
        for job in current_jobs:
            job.schedule_removal()
        await update.message.reply_text("Envios diários desativados. Use /start para reativar.")
    else:
        await update.message.reply_text("Nenhum envio diário ativo para este chat.")

# Função para enviar mensagem periódica
async def send_periodic_message(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    mensagem = get_asteroid_message()
    imagem = imagem_espacial_aleatoria()
    await send_message(chat_id, mensagem, imagem, context)

# Função principal
def main():
    
    # Inicializa o bot
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Adiciona os handlers para os comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    
    # Inicia o bot
    app.run_polling()

if __name__ == "__main__":
    main()
