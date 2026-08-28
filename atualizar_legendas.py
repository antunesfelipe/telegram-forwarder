import os
import json
import asyncio
from pyrogram import Client

# Lê as variáveis de ambiente
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
CANAL_ORIGEM = os.environ["CANAL_ORIGEM"].strip()
TELEGRAM_SESSION = os.environ["TELEGRAM_SESSION"]

async def main():
    # Inicializa o cliente com a session string
    app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=TELEGRAM_SESSION)
    legendas = set()

    async with app:
        # Tratamento flexível para o canal (ID numérico ou username)
        if CANAL_ORIGEM.replace("-", "").isdigit():
            chat_target = int(CANAL_ORIGEM)
        else:
            # Se for username e não tiver o '@', adiciona automaticamente
            chat_target = CANAL_ORIGEM if CANAL_ORIGEM.startswith("@") else f"@{CANAL_ORIGEM}"

        print(f"🔄 Conectando ao canal: {chat_target}...")
        
        try:
            chat = await app.get_chat(chat_target)
        except Exception as e:
            print(f"❌ Erro ao buscar chat '{chat_target}': {e}")
            print("💡 Dica: Se o canal for privado, confirme se o ID no GitHub Secrets começa com -100.")
            raise e

        print(f"📥 Extraindo histórico de {chat.title or chat.first_name}...")

        # Pega as últimas 1500 mensagens do canal de origem
        async for msg in app.get_chat_history(chat.id, limit=1500):
            txt = msg.caption or msg.text
            if txt:
                # Extrai a primeira linha (geralmente o título/legenda principal)
                primeira_linha = txt.strip().split('\n')[0].strip()
                if len(primeira_linha) > 2:
                    legendas.add(primeira_linha)

    # Ordena e salva em JSON
    resultado = sorted(list(legendas))
    with open("legendas.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    print(f"✅ Sucesso: {len(resultado)} legendas extraídas e salvas em legendas.json!")

if __name__ == "__main__":
    asyncio.run(main())
