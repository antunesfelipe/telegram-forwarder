import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
import json
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

async def executar_envio_stream(legenda1: str, legenda2: str):
    canal_origem = resolver_chat_id(os.environ["CANAL_ORIGEM"])
    canal_destino = resolver_chat_id(os.environ["CANAL_DESTINO"])
    buscas = [l for l in [legenda1, legenda2] if l]
    total_videos = len(buscas)
    
    app_pyro = obter_cliente_telegram()
    enviados = 0

    async with app_pyro:
        async for _ in app_pyro.get_dialogs(limit=200):
            pass

        yield f"data: {json.dumps({'status': 'info', 'msg': 'Iniciando busca no canal...'})}\n\n"
        await asyncio.sleep(0.1)

        for i, termo in enumerate(buscas):
            encontrado = False
            mensagens = []
            
            async for msg in app_pyro.get_chat_history(canal_origem, limit=3000):
                mensagens.append(msg)

            for idx, msg in enumerate(mensagens):
                txt = msg.caption or msg.text
                if txt and termo.lower() in txt.lower():
                    msg_video = None
                    legenda_texto = txt

                    if msg.video or msg.animation:
                        msg_video = msg
                    elif idx > 0:
                        msg_seguinte = mensagens[idx - 1]
                        if msg_seguinte.video or msg_seguinte.animation:
                            msg_video = msg_seguinte

                    if msg_video:
                        msg_status = "Baixando mídia do Telegram..."
                        yield f"data: {json.dumps({'status': 'info_video', 'index': i, 'msg': msg_status})}\n\n"
                        await asyncio.sleep(0.1)
                        
                        queue = asyncio.Queue()

                        # Progresso do Download (0% a 50% para o vídeo atual)
                        def progress_down(current, total):
                            pct = int((current / total) * 50)
                            queue.put_nowait(pct)

                        download_task = asyncio.create_task(
                            app_pyro.download_media(msg_video, progress=progress_down)
                        )

                        while not download_task.done() or not queue.empty():
                            while not queue.empty():
                                pct = queue.get_nowait()
                                yield f"data: {json.dumps({'status': 'progress', 'index': i, 'pct': pct})}\n\n"
                            await asyncio.sleep(0.1)

                        file_path = await download_task
                        
                        try:
                            msg_status = "Enviando mídia para destino..."
                            yield f"data: {json.dumps({'status': 'info_video', 'index': i, 'msg': msg_status})}\n\n"
                            await asyncio.sleep(0.1)

                            # Progresso do Upload (50% a 100% para o vídeo atual)
                            def progress_up(current, total):
                                pct = 50 + int((current / total) * 50)
                                queue.put_nowait(pct)

                            if msg_video.video:
                                upload_task = asyncio.create_task(
                                    app_pyro.send_video(chat_id=canal_destino, video=file_path, caption=legenda_texto, progress=progress_up)
                                )
                            else:
                                upload_task = asyncio.create_task(
                                    app_pyro.send_animation(chat_id=canal_destino, animation=file_path, caption=legenda_texto, progress=progress_up)
                                )

                            while not upload_task.done() or not queue.empty():
                                while not queue.empty():
                                    pct = queue.get_nowait()
                                    yield f"data: {json.dumps({'status': 'progress', 'index': i, 'pct': pct})}\n\n"
                                await asyncio.sleep(0.1)

                            await upload_task
                            
                            yield f"data: {json.dumps({'status': 'info_video', 'index': i, 'msg': 'Concluído com sucesso!'})}\n\n"
                            encontrado = True
                            enviados += 1
                        finally:
                            if file_path and os.path.exists(file_path):
                                os.remove(file_path)
                        break

            if not encontrado:
                yield f"data: {json.dumps({'status': 'error_video', 'index': i, 'msg': f'Vídeo não encontrado!'})}\n\n"

    yield f"data: {json.dumps({'status': 'done', 'msg': f'Processo concluído! {enviados} de {total_videos} vídeo(s) enviado(s).'})}\n\n"

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
