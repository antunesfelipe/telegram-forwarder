import asyncio
# Corrige o problema de event loop do Pyrogram no startup da Render
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
import json
from fastapi import FastAPI, HTTPException
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

    enviados = 0
    nao_encontrados = []

    async with app_pyro:
        # Carrega conversas para evitar erro de Peer ID
        async for _ in app_pyro.get_dialogs(limit=200):
            pass

        for termo in buscas:
            encontrado = False
            async for msg in app_pyro.get_chat_history(canal_origem, limit=3000):
                txt = msg.caption or msg.text
                if txt and termo.lower() in txt.lower():
                    # Método fallback de download/upload para burlar CHAT_FORWARDS_RESTRICTED
                    file_path = await app_pyro.download_media(msg)
                    
                    try:
                        if msg.video:
                            await app_pyro.send_video(chat_id=canal_destino, video=file_path, caption=msg.caption)
                        elif msg.photo:
                            await app_pyro.send_photo(chat_id=canal_destino, photo=file_path, caption=msg.caption)
                        elif msg.document:
                            await app_pyro.send_document(chat_id=canal_destino, document=file_path, caption=msg.caption)
                        else:
                            await app_pyro.send_message(chat_id=canal_destino, text=txt)
                    finally:
                        # Remove o arquivo do servidor local após o envio
                        if file_path and os.path.exists(file_path):
                            os.remove(file_path)

                    encontrado = True
                    enviados += 1
                    break
            
            if not encontrado:
                nao_encontrados.append(termo)

    if enviados == 0 and nao_encontrados:
        raise Exception(f"Nenhum vídeo encontrado para: {', '.join(nao_encontrados)}")

    msg_sucesso = f"{enviados} vídeo(s) enviado(s) com sucesso!"
    if nao_encontrados:
        msg_sucesso += f" (Não encontrados: {', '.join(nao_encontrados)})"

    return {"status": msg_sucesso}

# Rotas da API
@app.get("/")
def home():
    return {"status": "API Telegram Forwarder rodando com sucesso!"}

@app.get("/legendas")
def obter_legendas():
    if os.path.exists("legendas.json"):
        with open("legendas.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return []

@app.get("/varrer")
async def varrer():
    legendas_atualizadas = await executar_varredura()
    return legendas_atualizadas

@app.post("/enviar")
async def enviar(payload: EnvioPayload):
    if not payload.legenda1 and not payload.legenda2:
        raise HTTPException(status_code=400, detail="Forneça ao menos uma legenda.")

    try:
        resultado = await executar_envio(payload.legenda1, payload.legenda2)
        return resultado
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
