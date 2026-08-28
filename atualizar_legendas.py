import os
import json
import asyncio
from pyrogram import Client

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
CANAL_ORIGEM = os.environ["CANAL_ORIGEM"].strip()
TELEGRAM_SESSION = os.environ["TELEGRAM_SESSION"]

async def main():
    app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=TELEGRAM_SESSION)
    legendas = set()

    async with app:
        # 1. Converte o ID
        chat_id = int(CANAL_ORIGEM) if CANAL_ORIGEM.replace("-", "").isdigit() else CANAL_ORIGEM

        print("🔄 Carregando diálogos para registrar o canal na sessão...")
        # Força o Pyrogram a conhecer os chats da conta (resolve o erro Peer id invalid)
        async for dialog in app.get_dialogs(limit=100):
            pass

        print(f"📥 Buscando mensagens do canal ID: {chat_id}...")
        
        # Pega as mensagens (lendo até 500 para ser bem mais rápido)
        async for msg in app.get_chat_history(chat_id, limit=10000):
            txt = msg.caption or msg.text
            if txt:
                primeira_linha = txt.strip().split('\n')[0].strip()
                if len(primeira_linha) > 2:
                    legendas.add(primeira_linha)

    # Ordena e salva em JSON
    resultado = sorted(list(legendas))
    with open("legendas.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    print(f"✅ Sucesso: {len(resultado)} legendas extraídas e salvas!")

if __name__ == "__main__":
    asyncio.run(main())
