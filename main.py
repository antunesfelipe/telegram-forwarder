from fastapi import FastAPI, BackgroundTasks
import os, json, asyncio
from pyrogram import Client

app = FastAPI()

async def executar_varredura():
    api_id = int(os.environ["API_ID"])
    api_hash = os.environ["API_HASH"]
    canal_origem = os.environ["CANAL_ORIGEM"].strip()
    session = os.environ["TELEGRAM_SESSION"]

    app_pyro = Client("user_session", api_id=api_id, api_hash=api_hash, session_string=session)
    legendas = set()

    async with app_pyro:
        chat_id = int(canal_origem) if canal_origem.replace("-", "").isdigit() else canal_origem
        
        async for dialog in app_pyro.get_dialogs(limit=100):
            pass

        async for msg in app_pyro.get_chat_history(chat_id, limit=3000):
            txt = msg.caption or msg.text
            if txt:
                primeira_linha = txt.strip().split('\n')[0].strip()
                if len(primeira_linha) > 2:
                    legendas.add(primeira_linha)

    resultado = sorted(list(legendas))
    with open("legendas.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

@app.get("/varrer")
def varrer(background_tasks: BackgroundTasks):
    background_tasks.add_task(executar_varredura)
    return {"status": "Varredura iniciada em segundo plano!"}
