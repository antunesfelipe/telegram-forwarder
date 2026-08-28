import os
import json
import asyncio
from pyrogram import Client

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
CANAL_ORIGEM = os.environ["CANAL_ORIGEM"]
TELEGRAM_SESSION = os.environ["TELEGRAM_SESSION"]

async def main():
    app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=TELEGRAM_SESSION)
    legendas = set()

    async with app:
        # Resolve o ID/Username do canal
        chat_target = int(CANAL_ORIGEM) if CANAL_ORIGEM.replace("-", "").isdigit() else CANAL_ORIGEM
        chat = await app.get_chat(chat_target)
        
        # Pega as últimas 1500 mensagens do canal de origem
        async for msg in app.get_chat_history(chat.id, limit=1500):
            txt = msg.caption or msg.text
            if txt:
                # Extrai a primeira linha (geralmente o título/legenda principal)
                primeira_linha = txt.strip().split('\n')[0]
                if len(primeira_linha) > 2:
                    legendas.add(primeira_linha)

    # Ordena e salva em JSON
    resultado = sorted(list(legendas))
    with open("legendas.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    print(f"✅ Sucesso: {len(resultado)} legendas extraídas e salvas em legendas.json!")

if __name__ == "__main__":
    asyncio.run(main())
