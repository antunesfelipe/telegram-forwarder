import os
import re
import asyncio
import sys
import unicodedata
from pyrogram import Client

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
CANAL_ORIGEM = os.environ["CANAL_ORIGEM"]
CANAL_DESTINO = os.environ["CANAL_DESTINO"]
TELEGRAM_SESSION = os.environ["TELEGRAM_SESSION"]
LEGENDA_BUSCA = os.environ.get("LEGENDA_BUSCA", "").strip()

def normalizar_texto(texto):
    if not texto: return ""
    txt = texto.lower()
    txt = unicodedata.normalize('NFD', txt).encode('ascii', 'ignore').decode('utf-8')
    txt = re.sub(r'http\S+|www\.\S+', '', txt)
    txt = re.sub(r'[^\w\s]', '', txt)
    return ' '.join(txt.split())

async def carregar_cache_dialogos(app):
    async for dialog in app.get_dialogs(limit=50): pass

async def resolver_chat_seguro(app, identificador):
    ident = str(identificador).strip()
    try:
        val = int(ident)
        try: return await app.get_chat(val)
        except Exception:
            await carregar_cache_dialogos(app)
            return await app.get_chat(val)
    except ValueError: pass

    if not ident.startswith("@"): ident = f"@{ident}"
    return await app.get_chat(ident)

async def main():
    if not LEGENDA_BUSCA:
        print("❌ Nenhuma legenda foi informada.")
        sys.exit(1)

    termo_alvo = normalizar_texto(LEGENDA_BUSCA)
    print(f"🔍 Procurando vídeo no canal pela legenda: \"{LEGENDA_BUSCA}\"...", flush=True)

    app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=TELEGRAM_SESSION)

    async with app:
        chat_origem_obj = await resolver_chat_seguro(app, CANAL_ORIGEM)
        chat_destino_obj = await resolver_chat_seguro(app, CANAL_DESTINO)

        encontrado = False

        # Busca até 3000 mensagens mais recentes
        async for msg in app.get_chat_history(chat_origem_obj.id, limit=3000):
            if not msg.video: continue

            # Tenta encontrar texto/legenda na propria mensagem ou nas 4 mensagens ao redor (ID -2 até ID +2)
            ids_vizinhos = list(range(msg.id - 2, msg.id + 3))
            msgs_vizinhas = await app.get_messages(chat_origem_obj.id, ids_vizinhos)

            legenda_extraida = msg.caption.strip() if msg.caption else None

            if not legenda_extraida and msgs_vizinhas:
                for m in msgs_vizinhas:
                    if m and not m.empty:
                        txt = m.caption or m.text
                        if txt:
                            legenda_extraida = txt.strip()
                            break

            if legenda_extraida:
                leg_norm = normalizar_texto(legenda_extraida)

                if termo_alvo in leg_norm:
                    print(f"🎯 Vídeo Encontrado! ID: {msg.id}", flush=True)
                    
                    print("📥 Baixando apenas o arquivo de vídeo...", flush=True)
                    caminho_video = await app.download_media(msg)

                    print("📤 Enviando vídeo com legenda para o canal destino...", flush=True)
                    await app.send_video(
                        chat_id=chat_destino_obj.id, 
                        video=caminho_video, 
                        caption=legenda_extraida
                    )

                    if os.path.exists(caminho_video): 
                        os.remove(caminho_video)

                    print("✅ Vídeo enviado com sucesso!", flush=True)
                    encontrado = True
                    break

        if not encontrado:
            print("⚠️ Nenhuma postagem de vídeo foi encontrada para essa legenda.")
            sys.exit(1) # Faz o GitHub Actions registrar a falha corretamente no painel

if __name__ == "__main__":
    asyncio.run(main())
