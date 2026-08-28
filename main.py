import asyncio
# Corrige o problema de event loop do Pyrogram no startup da Render
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
import json
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pyrogram import Client

app = FastAPI()

# Permite que o seu site faça requisições para a Render sem erro de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class EnvioPayload(BaseModel):
    legenda1: str = ""
    legenda2: str = ""

# Funções Auxiliares
def obter_cliente_telegram():
    api_id = int(os.environ["API_ID"])
    api_hash = os.environ["API_HASH"]
    session = os.environ["TELEGRAM_SESSION"]
    return Client("user_session", api_id=api_id, api_hash=api_hash, session_string=session)

def resolver_chat_id(valor: str):
    valor = valor.strip()
    if valor.startswith("-") and valor[1:].isdigit():
        return int(valor)
    if valor.isdigit():
        return int(valor)
    return valor

async def executar_varredura():
    canal_origem = resolver_chat_id(os.environ["CANAL_ORIGEM"])
    app_pyro = obter_cliente_telegram()
    legendas = set()

    async with app_pyro:
        # Carrega os diálogos para esquentar o cache de conversas do Pyrogram
        async for _ in app_pyro.get_dialogs(limit=100):
            pass

        # Varrer até 5.000 mensagens
        async for msg in app_pyro.get_chat_history(canal_origem, limit=5000):
            txt = msg.caption or msg.text
            if txt:
                primeira_linha = txt.strip().split('\n')[0].strip()
                if len(primeira_linha) > 2:
                    legendas.add(primeira_linha)

    resultado = sorted(list(legendas))
    
    # Salva localmente na Render
    with open("legendas.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
        
    return resultado

async def executar_envio(legenda1: str, legenda2: str):
    canal_origem = resolver_chat_id(os.environ["CANAL_ORIGEM"])
    canal_destino = resolver_chat_id(os.environ["CANAL_DESTINO"])
    
    buscas = [l for l in [legenda1, legenda2] if l]
    app_pyro = obter_cliente_telegram()

    async with app_pyro:
        async for _ in app_pyro.get_dialogs(limit=100):
            pass

        for termo in buscas:
            encontrado = False
            async for msg in app_pyro.get_chat_history(canal_origem, limit=3000):
                txt = msg.caption or msg.text
                if txt and termo.lower() in txt.lower():
                    # Copia a mídia/mensagem para o canal de destino
                    await msg.copy(canal_destino)
                    encontrado = True
                    break
            
            if not encontrado:
                print(f"Alerta: Nenhuma mídia encontrada para a legenda: {termo}")

# Rotas da API
@app.get("/")
def home():
    return {"status": "API Telegram Forwarder rodando com sucesso!"}

# ROTA NOVA: Devolve as legendas salvas na Render para a tela
@app.get("/legendas")
def obter_legendas():
    if os.path.exists("legendas.json"):
        with open("legendas.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return []

# ROTA AJUSTADA: Executa a varredura e já devolve a lista atualizada
@app.get("/varrer")
async def varrer():
    legendas_atualizadas = await executar_varredura()
    return legendas_atualizadas

@app.post("/enviar")
async def enviar(payload: EnvioPayload, background_tasks: BackgroundTasks):
    if not payload.legenda1 and not payload.legenda2:
        raise HTTPException(status_code=400, detail="Forneça ao menos uma legenda.")

    background_tasks.add_task(executar_envio, payload.legenda1, payload.legenda2)
    return {"status": "Envio processado em segundo plano!"}
