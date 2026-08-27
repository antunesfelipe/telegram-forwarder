import os
import re
import asyncio
import sys
from pyrogram import Client, enums

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
CANAL_ORIGEM = os.environ["CANAL_ORIGEM"]
CANAL_DESTINO = os.environ["CANAL_DESTINO"]
TELEGRAM_SESSION = os.environ["TELEGRAM_SESSION"]
LEGENDA_BUSCA = os.environ.get("LEGENDA_BUSCA", "").strip()

def normalizar_texto(texto):
    if not texto: return ""
    txt = texto.lower()
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
        ultima_legenda_visto = None

        # Percorre o histórico mensagem por mensagem sem estourar limite do Telegram
        async for msg in app.get_chat_history(chat_origem_obj.id, limit=1500):
            # Armazena o texto/legenda se a mensagem atual for texto ou foto
            if msg.text:
                ultima_legenda_visto = msg.text.strip()
            elif msg.caption:
                ultima_legenda_visto = msg.caption.strip()

            if not msg.video:
                continue

            # Se o próprio vídeo já tiver legenda, usa ela; caso contrário, pega a legenda mais recente vista
            legenda_final = msg.caption.strip() if msg.caption else ultima_legenda_visto

            if legenda_final:
                leg_norm = normalizar_texto(legenda_final)

                if termo_alvo in leg_norm:
                    print(f"🎯 Vídeo Encontrado! ID: {msg.id}", flush=True)
                    
                    print("📥 Baixando arquivo de vídeo...", flush=True)
                    caminho_video = await app.download_media(msg)

                    print("📤 Enviando vídeo com legenda para o canal destino...", flush=True)
                    await app.send_video(
                        chat_id=chat_destino_obj.id, 
                        video=caminho_video, 
                        caption=legenda_final
                    )

                    if os.path.exists(caminho_video): 
                        os.remove(caminho_video)

                    print("✅ Vídeo enviado com sucesso!", flush=True)
                    encontrado = True
                    break

            # Pausa de 100ms a cada vídeo para evitar FloodWait
            await asyncio.sleep(0.1)

        if not encontrado:
            print("⚠️ Nenhuma postagem de vídeo foi encontrada para essa legenda.")

if __name__ == "__main__":
    asyncio.run(main())
