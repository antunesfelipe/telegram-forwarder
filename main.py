import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
import json
import tempfile
import gc
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pyrogram import Client

estado_envio = {
    "em_andamento": False,
    "concluido": False,
    "msg_final": "",
    "videos": []
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Servidor iniciando... Rodando varredura automática...")
    try:
        await executar_varredura()
        print("✅ Varredura concluída!")
    except Exception as e:
        print(f"⚠️ Erro na varredura: {e}")
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
    # Configurado para limitar o uso de memória interna do cliente Telegram
    return Client(
        "user_session", 
        api_id=api_id, 
        api_hash=api_hash, 
        session_string=session,
        max_concurrent_transfers=1 # Força 1 transferência por vez para economizar RAM
    )

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
        async for msg in app_pyro.get_chat_history(canal_origem, limit=2000):
            txt = msg.caption or msg.text
            if txt:
                primeira_linha = txt.strip().split('\n')[0].strip()
                if len(primeira_linha) > 2:
                    legendas.add(primeira_linha)

    resultado = sorted(list(legendas))
    with open("legendas.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    
    gc.collect() # Libera RAM após varredura
    return resultado

async def processar_envio_background(legenda1: str, legenda2: str):
    global estado_envio
    canal_origem = resolver_chat_id(os.environ["CANAL_ORIGEM"])
    canal_destino = resolver_chat_id(os.environ["CANAL_DESTINO"])
    buscas = [l for l in [legenda1, legenda2] if l]
    total_videos = len(buscas)
    
    estado_envio["em_andamento"] = True
    estado_envio["concluido"] = False
    estado_envio["msg_final"] = ""
    estado_envio["videos"] = [{"msg": "Buscando mídia...", "pct": 0, "status": "progress"} for _ in buscas]

    app_pyro = obter_cliente_telegram()
    enviados = 0

    temp_dir = os.path.join(tempfile.gettempdir(), "telegram_downloads")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        async with app_pyro:
            for i, termo in enumerate(buscas):
                encontrado = False
                
                # Busca direta otimizada
                async for msg in app_pyro.search_messages(canal_origem, query=termo, limit=5):
                    txt = msg.caption or msg.text
                    if txt and termo.lower() in txt.lower():
                        msg_video = msg if (msg.video or msg.animation) else None
                        
                        if msg_video:
                            estado_envio["videos"][i]["msg"] = "Baixando mídia..."
                            
                            def progress_down(current, total):
                                pct = int((current / total) * 50)
                                estado_envio["videos"][i]["pct"] = pct

                            caminho_destino = os.path.join(temp_dir, f"vid_{i}_{msg_video.id}.mp4")
                            file_path = await app_pyro.download_media(msg_video, file_name=caminho_destino, progress=progress_down)
                            
                            try:
                                estado_envio["videos"][i]["msg"] = "Enviando mídia..."

                                def progress_up(current, total):
                                    pct = 50 + int((current / total) * 50)
                                    estado_envio["videos"][i]["pct"] = pct

                                # Envia como documento para reduzir o consumo do processador do Render na conversão
                                if msg_video.video:
                                    await app_pyro.send_video(chat_id=canal_destino, video=file_path, caption=txt, progress=progress_up)
                                else:
                                    await app_pyro.send_animation(chat_id=canal_destino, animation=file_path, caption=txt, progress=progress_up)

                                estado_envio["videos"][i]["msg"] = "Concluído com sucesso!"
                                estado_envio["videos"][i]["pct"] = 100
                                encontrado = True
                                enviados += 1
                            finally:
                                if file_path and os.path.exists(file_path):
                                    os.remove(file_path)
                                gc.collect() # Força limpeza da memória após cada vídeo
                            break

                if not encontrado:
                    estado_envio["videos"][i]["msg"] = "Vídeo não encontrado!"
                    estado_envio["videos"][i]["status"] = "error"

        estado_envio["msg_final"] = f"Processo concluído! {enviados} de {total_videos} vídeo(s) enviado(s)."
    except Exception as e:
        estado_envio["msg_final"] = f"Erro no processo: {str(e)}"
    finally:
        estado_envio["concluido"] = True
        estado_envio["em_andamento"] = False
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
    return await executar_varredura()

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
