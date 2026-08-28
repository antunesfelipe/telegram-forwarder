import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pyrogram import Client

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Servidor iniciando... Rodando varredura automática de legendas...")
    try:
        await executar_varredura()
        print("✅ Varredura inicial concluída com sucesso!")
    except Exception as e:
        print(f"⚠️ Erro na varredura inicial: {e}")
    yield

app = FastAPI(lifespan=lifespan)

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
        async for _ in app_pyro.get_dialogs(limit=100):
            pass

        async for msg in app_pyro.get_chat_history(canal_origem, limit=5000):
            txt = msg.caption or msg.text
            if txt:
                primeira_linha = txt.strip().split('\n')[0].strip()
                if len(primeira_linha) > 2:
                    legendas.add(primeira_linha)

    resultado = sorted(list(legendas))
    
    with open("legendas.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
        
    return resultado

# Função geradora de eventos SSE para progresso em tempo real
async def executar_envio_stream(legenda1: str, legenda2: str):
    canal_origem = resolver_chat_id(os.environ["CANAL_ORIGEM"])
    canal_destino = resolver_chat_id(os.environ["CANAL_DESTINO"])
    buscas = [l for l in [legenda1, legenda2] if l]
    
    app_pyro = obter_cliente_telegram()
    enviados = 0

    async with app_pyro:
        async for _ in app_pyro.get_dialogs(limit=200):
            pass

        yield f"data: {json.dumps({'status': 'info', 'msg': 'Buscando mensagens no canal...'})}\n\n"

        for termo in buscas:
            encontrado = False
            mensagens = []
            async for msg in app_pyro.get_chat_history(canal_origem, limit=3000):
                mensagens.append(msg)

            for idx, msg in enumerate(mensagens):
                txt = msg.caption or msg.text
                if txt and termo.lower() in txt.lower():
                    msg_video = None
                    legenda_texto = txt

                    # 1. Se a própria mensagem for vídeo/gif
                    if msg.video or msg.animation:
                        msg_video = msg
                    # 2. Se for texto puro, pega a mensagem enviada logo abaixo (mensagem seguinte)
                    elif idx > 0:
                        msg_seguinte = mensagens[idx - 1]
                        if msg_seguinte.video or msg_seguinte.animation:
                            msg_video = msg_seguinte

                    if msg_video:
                        yield f"data: {json.dumps({'status': 'info', 'msg': f'Baixando mídia para: {termo}...'})}\n\n"
                        
                        file_path = await app_pyro.download_media(msg_video)
                        
                        try:
                            # Callback para calcular a porcentagem de upload
                            def progress_callback(current, total):
                                pct = int((current / total) * 100)
                                asyncio.create_task(
                                    # Notifica o progresso do upload
                                    app.state.event_queue.put({'status': 'progress', 'pct': pct, 'termo': termo})
                                )

                            yield f"data: {json.dumps({'status': 'progress', 'pct': 10, 'termo': termo})}\n\n"
                            
                            if msg_video.video:
                                await app_pyro.send_video(
                                    chat_id=canal_destino, 
                                    video=file_path, 
                                    caption=legenda_texto
                                )
                            elif msg_video.animation:
                                await app_pyro.send_animation(
                                    chat_id=canal_destino, 
                                    animation=file_path, 
                                    caption=legenda_texto
                                )
                            
                            yield f"data: {json.dumps({'status': 'progress', 'pct': 100, 'termo': termo})}\n\n"
                            encontrado = True
                            enviados += 1
                        finally:
                            if file_path and os.path.exists(file_path):
                                os.remove(file_path)
                        break

            if not encontrado:
                yield f"data: {json.dumps({'status': 'error', 'msg': f'Vídeo não encontrado para: {termo}'})}\n\n"

    yield f"data: {json.dumps({'status': 'done', 'msg': f'Processo concluído! {enviados} vídeo(s) enviado(s).'})}\n\n"

# Rotas
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
    return await executar_varredura()

@app.post("/enviar")
async def enviar(payload: EnvioPayload):
    if not payload.legenda1 and not payload.legenda2:
        raise HTTPException(status_code=400, detail="Forneça ao menos uma legenda.")

    return StreamingResponse(
        executar_envio_stream(payload.legenda1, payload.legenda2),
        media_type="text/event-stream"
    )
