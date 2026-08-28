import os
import re
import asyncio
import sys
import unicodedata
from pyrogram import Client, enums

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
CANAL_ORIGEM = os.environ["CANAL_ORIGEM"]
CANAL_DESTINO = os.environ["CANAL_DESTINO"]
TELEGRAM_SESSION = os.environ["TELEGRAM_SESSION"]
LEGENDA_INPUT = os.environ.get("LEGENDA_BUSCA", "").strip()

def normalizar_texto(texto):
    if not texto: return ""
    txt = texto.lower()
    txt = unicodedata.normalize('NFD', txt).encode('ascii', 'ignore').decode('utf-8')
    txt = re.sub(r'http\S+|www\.\S+', '', txt)
    txt = re.sub(r'[^\w\s]', '', txt)
    return ' '.join(txt.split())

async def carregar_cache_dialogos(app):
    async for dialog in app.get_dialogs(limit=30): pass

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

async def buscar_e_enviar_video(app, chat_origem_obj, chat_destino_obj, legenda_busca):
    termo_alvo = normalizar_texto(legenda_busca)
    print(f"\n⚡ [TURBO] Buscando instantaneamente: \"{legenda_busca}\"...", flush=True)

    mensagens_encontradas = []
    try:
        async for m in app.search_messages(chat_origem_obj.id, query=legenda_busca, limit=20):
            mensagens_encontradas.append(m)
    except Exception as e:
        print(f"Aviso na busca direta: {e}", flush=True)

    for msg_alvo in mensagens_encontradas:
        if msg_alvo.video:
            leg = msg_alvo.caption or legenda_busca
            print(f"🎯 Vídeo Encontrado Direto! ID: {msg_alvo.id}", flush=True)
            return await baixar_e_enviar(app, chat_origem_obj, chat_destino_obj, msg_alvo, leg)
        else:
            ids_proximos = [msg_alvo.id + 1, msg_alvo.id + 2, msg_alvo.id - 1]
            for pid in ids_proximos:
                try:
                    vmsg = await app.get_messages(chat_origem_obj.id, pid)
                    if vmsg and vmsg.video:
                        print(f"🎯 Vídeo Encontrado via texto associado! ID: {vmsg.id}", flush=True)
                        return await baixar_e_enviar(app, chat_origem_obj, chat_destino_obj, vmsg, msg_alvo.text or msg_alvo.caption or legenda_busca)
                except Exception:
                    continue

    print("⚠️ Busca direta não achou. Varrendo os vídeos recentes...", flush=True)
    async for msg in app.get_chat_history(chat_origem_obj.id, limit=300):
        if not msg.video: continue

        legenda_extraida = msg.caption.strip() if msg.caption else None

        if not legenda_extraida:
            try:
                vizinhos = await app.get_messages(chat_origem_obj.id, [msg.id - 1, msg.id - 2])
                for v in vizinhos:
                    if v and (v.caption or v.text):
                        legenda_extraida = (v.caption or v.text).strip()
                        break
            except Exception: pass

        if legenda_extraida and termo_alvo in normalizar_texto(legenda_extraida):
            print(f"🎯 Vídeo Encontrado! ID: {msg.id}", flush=True)
            return await baixar_e_enviar(app, chat_origem_obj, chat_destino_obj, msg, legenda_extraida)

    return False

async def baixar_e_enviar(app, chat_origem_obj, chat_destino_obj, msg_video, legenda):
    print("📥 Baixando vídeo...", flush=True)
    caminho_video = await app.download_media(msg_video)

    print("📤 Enviando para o destino...", flush=True)
    await app.send_video(
        chat_id=chat_destino_obj.id, 
        video=caminho_video, 
        caption=legenda
    )

    if os.path.exists(caminho_video): 
        os.remove(caminho_video)

    print("✅ Concluído!", flush=True)
    return True

async def main():
    if not LEGENDA_INPUT:
        print("❌ Nenhuma legenda informada.")
        sys.exit(1)

    legendas = [l.strip() for l in LEGENDA_INPUT.split("|||") if l.strip()]
    app = Client("user_session", api_id=API_ID, api_hash=API_HASH, session_string=TELEGRAM_SESSION)

    async with app:
        chat_origem_obj = await resolver_chat_seguro(app, CANAL_ORIGEM)
        chat_destino_obj = await resolver_chat_seguro(app, CANAL_DESTINO)

        sucessos = 0
        for leg in legendas:
            ok = await buscar_e_enviar_video(app, chat_origem_obj, chat_destino_obj, leg)
            if ok: sucessos += 1

        if sucessos == 0:
            print("⚠️ Vídeo não encontrado.")
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
