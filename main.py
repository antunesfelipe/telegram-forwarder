import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
import json
import tempfile
import gc
import shutil
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pyrogram import Client

# Limita o uso de memória do garbage collector
gc.set_threshold(100, 5, 5)

estado_envio = {
    "em_andamento": False,
    "concluido": False,
    "msg_final": "",
    "videos": []
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Servidor iniciando em modo de economia extrema de RAM...")
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
    return Client(
        "user_session", 
        api_id=api_id, 
        api_hash=api_hash, 
        session_string=session,
        max_concurrent_transfers=1  # Evita baixar/enviar múltiplos blocos ao mesmo tempo para economizar RAM
    )

async def obter_peer_chat(app_pyro: Client, valor: str):
    valor_str = str(valor).strip()
    if "t.me/" in valor_str or valor_str.startswith("@"):
        chat = await app_pyro.get_chat(valor_str)
        return chat.id
        
    if valor_str.startswith("-") and valor_str[1:].isdigit():
        chat_id = int(valor_str)
        try:
            chat = await app_pyro.get_chat(chat_id)
            return chat.id
        except Exception:
            async for dialog in app_pyro.get_dialogs():
                if dialog.chat.id == chat_id:
                    return dialog.chat.id
            raise ValueError(f"Canal {chat_id} não encontrado na sessão.")
            
    return valor_str

async def executar_varredura():
    app_pyro = obter_cliente_telegram()
    legendas = set()

    async with app_pyro:
        canal_origem_raw = os.environ.get("CANAL_ORIGEM", "")
        canal_origem = await obter_peer_chat(app_pyro, canal_origem_raw)
        
        async for msg in app_pyro.get_chat_history(canal_origem, limit=2000):
            txt = msg.caption or msg.text
            if txt:
                primeira_linha = txt.strip().split('\n')[0].strip()
                if len(primeira_linha) > 2:
                    legendas.add(primeira_linha)

    resultado = sorted(list(legendas))
    with open("legendas.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    
    gc.collect()
    return resultado

async def processar_envio_background(legenda1: str, legenda2: str):
    global estado_envio
    buscas = [l.strip() for l in [legenda1, legenda2] if l and l.strip()]
    total_videos = len(buscas)
    
    estado_envio["em_andamento"] = True
    estado_envio["concluido"] = False
    estado_envio["msg_final"] = ""
    estado_envio["videos"] = [{"msg": "Aguardando...", "pct": 0, "status": "progress"} for _ in buscas]

    app_pyro = obter_cliente_telegram()
    enviados = 0

    temp_dir = os.path.join(tempfile.gettempdir(), "telegram_downloads")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
    os.makedirs(temp_dir, exist_ok=True)

    try:
        async with app_pyro:
            canal_origem = await obter_peer_chat(app_pyro, os.environ.get("CANAL_ORIGEM", ""))
            canal_destino = await obter_peer_chat(app_pyro, os.environ.get("CANAL_DESTINO", ""))

            for i, termo in enumerate(buscas):
                termo_limpo = " ".join(termo.strip().split()).lower()
                encontrado = False
                
                estado_envio["videos"][i]["msg"] = f"Buscando vídeo {i+1} no canal..."
                estado_envio["videos"][i]["pct"] = 5
                
                async for msg in app_pyro.get_chat_history(canal_origem, limit=1000):
                    txt = msg.caption or msg.text or ""
                    txt_limpo = " ".join(txt.strip().split()).lower()
                    
                    if txt_limpo and termo_limpo in txt_limpo:
                        if msg.video or msg.animation or msg.document:
                            estado_envio["videos"][i]["msg"] = "Baixando mídia por partes..."
                            estado_envio["videos"][i]["pct"] = 10
                            
                            def progress_down(current, total):
                                pct = 10 + int((current / total) * 45)
                                estado_envio["videos"][i]["pct"] = pct
                                # Força limpeza de buffers temporários de download
                                if current % (5 * 1024 * 1024) == 0:  # A cada 5MB
                                    gc.collect()

                            caminho_destino = os.path.join(temp_dir, f"vid_{i}_{msg.id}.mp4")
                            file_path = await app_pyro.download_media(msg, file_name=caminho_destino, progress=progress_down)
                            
                            # Limpeza agressiva pós-download
                            gc.collect()

                            try:
                                estado_envio["videos"][i]["msg"] = "Enviando mídia..."

                                def progress_up(current, total):
                                    pct = 55 + int((current / total) * 43)
                                    estado_envio["videos"][i]["pct"] = pct
                                    if current % (5 * 1024 * 1024) == 0:
                                        gc.collect()

                                caption_enviar = msg.caption or txt
                                if msg.video:
                                    await app_pyro.send_video(chat_id=canal_destino, video=file_path, caption=caption_enviar, progress=progress_up)
                                elif msg.animation:
                                    await app_pyro.send_animation(chat_id=canal_destino, animation=file_path, caption=caption_enviar, progress=progress_up)
                                else:
                                    await app_pyro.send_document(chat_id=canal_destino, document=file_path, caption=caption_enviar, progress=progress_up)

                                estado_envio["videos"][i]["msg"] = "Concluído com sucesso!"
                                estado_envio["videos"][i]["pct"] = 100
                                encontrado = True
                                enviados += 1
                            finally:
                                # Deleta o arquivo baixado IMEDIATAMENTE para liberar espaço no disco do Render
                                if file_path and os.path.exists(file_path):
                                    os.remove(file_path)
                                gc.collect()
                            break

                if not encontrado:
                    estado_envio["videos"][i]["msg"] = "Vídeo não encontrado!"
                    estado_envio["videos"][i]["status"] = "error"
                    estado_envio["videos"][i]["pct"] = 0

        estado_envio["msg_final"] = f"Processo concluído! {enviados} de {total_videos} vídeo(s) enviado(s)."
    except Exception as e:
        estado_envio["msg_final"] = f"Erro no processo: {str(e)}"
    finally:
        estado_envio["concluido"] = True
        estado_envio["em_andamento"] = False
        shutil.rmtree(temp_dir, ignore_errors=True)
        gc.collect()

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
    try:
        return await executar_varredura()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/status_progresso")
def status_progresso():
    return estado_envio

@app.post("/enviar")
async def enviar(payload: EnvioPayload, background_tasks: BackgroundTasks):
    if not payload.legenda1 and not payload.legenda2:
        raise HTTPException(status_code=400, detail="Forneça ao menos uma legenda.")

    if estado_envio["em_andamento"]:
        raise HTTPException(status_code=400, detail="Já existe um envio em andamento.")

    background_tasks.add_task(processar_envio_background, payload.legenda1, payload.legenda2)
    return {"status": "iniciado"}
