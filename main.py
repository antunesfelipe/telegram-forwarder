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
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pyrogram import Client

# Limites mais agressivos para o coletor de lixo do Python
gc.set_threshold(20, 3, 3)

SERVER_RUN_ID = str(int(time.time()))

estado_envio = {
    "server_id": SERVER_RUN_ID,
    "em_andamento": False,
    "concluido": False,
    "erro_fatal": False,
    "msg_final": "",
    "videos": []
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"🚀 Servidor iniciando... [ID: {SERVER_RUN_ID}]")
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
    return Client(
        "user_session", 
        api_id=int(os.environ["API_ID"]), 
        api_hash=os.environ["API_HASH"], 
        session_string=os.environ["TELEGRAM_SESSION"],
        workers=1,
        max_concurrent_transmissions=1
    )

async def resolver_canal(app_pyro: Client, valor: str):
    valor_str = str(valor).strip()
    if not valor_str:
        raise ValueError("Variável de canal não configurada.")
        
    if "t.me/" in valor_str or valor_str.startswith("@"):
        chat = await app_pyro.get_chat(valor_str)
        return chat.id

    if valor_str.startswith("-") and valor_str[1:].isdigit():
        chat_id = int(valor_str)
        try:
            chat = await app_pyro.get_chat(chat_id)
            return chat.id
        except Exception:
            pass

        async for dialog in app_pyro.get_dialogs(limit=300):
            if dialog.chat.id == chat_id:
                return dialog.chat.id
        return chat_id

    return valor_str

async def processar_envio_background(legenda1: str, legenda2: str):
    global estado_envio
    buscas = [l.strip() for l in [legenda1, legenda2] if l and l.strip()]
    total_videos = len(buscas)
    
    estado_envio["em_andamento"] = True
    estado_envio["concluido"] = False
    estado_envio["erro_fatal"] = False
    estado_envio["msg_final"] = ""
    estado_envio["videos"] = [{"msg": "Aguardando...", "pct": 0, "status": "progress"} for _ in buscas]

    app_pyro = obter_cliente_telegram()
    enviados = 0

    temp_dir = os.path.join(tempfile.gettempdir(), "tg_down")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
    os.makedirs(temp_dir, exist_ok=True)

    try:
        async with app_pyro:
            canal_origem = await resolver_canal(app_pyro, os.environ.get("CANAL_ORIGEM", ""))
            canal_destino = await resolver_canal(app_pyro, os.environ.get("CANAL_DESTINO", ""))

            for i, termo in enumerate(buscas):
                termo_normalizado = " ".join(termo.strip().split()).lower()
                encontrado = False
                
                estado_envio["videos"][i]["msg"] = f"Buscando vídeo {i+1}..."
                estado_envio["videos"][i]["pct"] = 5
                
                mensagens = [m async for m in app_pyro.get_chat_history(canal_origem, limit=1500)]
                
                for index, msg in enumerate(mensagens):
                    txt = msg.caption or msg.text or ""
                    txt_normalizado = " ".join(txt.strip().split()).lower()
                    
                    if txt_normalizado and (termo_normalizado in txt_normalizado or txt_normalizado in termo_normalizado):
                        msg_video = None
                        caption_enviar = txt

                        if msg.video or msg.animation or msg.document:
                            msg_video = msg
                        else:
                            for offset in range(1, 4):
                                if index - offset >= 0:
                                    m_prox = mensagens[index - offset]
                                    if m_prox.video or m_prox.animation or m_prox.document:
                                        msg_video = m_prox
                                        break
                        
                        if msg_video:
                            tamanho_total = getattr(msg_video.video or msg_video.document or msg_video.animation, "file_size", 0)
                            
                            espaco_livre = shutil.disk_usage(temp_dir).free
                            if tamanho_total > 0 and espaco_livre < tamanho_total:
                                raise Exception(f"Sem espaço em disco. Necessário: {tamanho_total // (1024**2)}MB, Livre: {espaco_livre // (1024**2)}MB")

                            estado_envio["videos"][i]["msg"] = "Baixando (Modo de Baixa Memória)..."
                            caminho_arquivo = os.path.join(temp_dir, f"vid_{i}.mp4")
                            
                            last_update = time.time()
                            bytes_baixados = 0
                            bytes_desde_ultimo_gc = 0

                            with open(caminho_arquivo, "wb") as f:
                                async for chunk in app_pyro.stream_media(msg_video):
                                    f.write(chunk)
                                    len_chunk = len(chunk)
                                    bytes_baixados += len_chunk
                                    bytes_desde_ultimo_gc += len_chunk

                                    if time.time() - last_update > 0.5:
                                        if tamanho_total > 0:
                                            pct = 5 + int((bytes_baixados / tamanho_total) * 45)
                                        else:
                                            pct = 25
                                        estado_envio["videos"][i]["pct"] = pct
                                        last_update = time.time()

                                    if bytes_desde_ultimo_gc >= 10485760:
                                        gc.collect()
                                        bytes_desde_ultimo_gc = 0

                            gc.collect()
                            estado_envio["videos"][i]["pct"] = 50

                            try:
                                estado_envio["videos"][i]["msg"] = "Enviando mídia..."
                                last_up = time.time()
                                def cb_up(current, total):
                                    nonlocal last_up
                                    if time.time() - last_up > 0.5:
                                        pct = 50 + int((current / total) * 48)
                                        estado_envio["videos"][i]["pct"] = pct
                                        last_up = time.time()

                                if msg_video.video:
                                    await app_pyro.send_video(chat_id=canal_destino, video=caminho_arquivo, caption=caption_enviar, progress=cb_up)
                                elif msg_video.animation:
                                    await app_pyro.send_animation(chat_id=canal_destino, animation=caminho_arquivo, caption=caption_enviar, progress=cb_up)
                                else:
                                    await app_pyro.send_document(chat_id=canal_destino, document=caminho_arquivo, caption=caption_enviar, progress=cb_up)

                                estado_envio["videos"][i]["msg"] = "Concluído!"
                                estado_envio["videos"][i]["pct"] = 100
                                encontrado = True
                                enviados += 1
                            finally:
                                if os.path.exists(caminho_arquivo):
                                    os.remove(caminho_arquivo)
                                gc.collect()
                            break

                if not encontrado:
                    estado_envio["videos"][i]["msg"] = "Não encontrado!"
                    estado_envio["videos"][i]["status"] = "error"
                    estado_envio["videos"][i]["pct"] = 0

        estado_envio["msg_final"] = f"Concluído! {enviados} de {total_videos} vídeo(s) enviado(s)."
    except Exception as e:
        estado_envio["erro_fatal"] = True
        estado_envio["msg_final"] = f"Erro no servidor: {str(e)}"
    finally:
        estado_envio["concluido"] = True
        estado_envio["em_andamento"] = False
        shutil.rmtree(temp_dir, ignore_errors=True)
        gc.collect()

@app.get("/")
def home():
    return {"status": "ok"}

@app.get("/legendas")
def obter_legendas():
    if os.path.exists("legendas.json"):
        with open("legendas.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return []

@app.get("/varrer")
async def varrer_canal():
    app_pyro = obter_cliente_telegram()
    legendas = []
    try:
        async with app_pyro:
            canal_origem = await resolver_canal(app_pyro, os.environ.get("CANAL_ORIGEM", ""))
            
            async for msg in app_pyro.get_chat_history(canal_origem, limit=1500):
                txt = msg.caption or msg.text or ""
                txt_limpo = " ".join(txt.strip().split())
                if txt_limpo and txt_limpo not in legendas:
                    legendas.append(txt_limpo)
        
        with open("legendas.json", "w", encoding="utf-8") as f:
            json.dump(legendas, f, ensure_ascii=False, indent=4)
            
        return legendas
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao varrer canal: {str(e)}")

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
    return {"status": "iniciado", "server_id": SERVER_RUN_ID}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
