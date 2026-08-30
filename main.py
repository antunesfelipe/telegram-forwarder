# ===== MIGRAÇÃO COMPLETA DE CANAL =====

estado_migracao = {
    "em_andamento": False,
    "concluido": False,
    "erro_fatal": False,
    "total": 0,
    "processados": 0,
    "enviados": 0,
    "falhas": 0,
    "msg_atual": "",
    "msg_final": ""
}

class MigracaoPayload(BaseModel):
    origem: str = "-1003810645631"
    destino: str = "-5420437663"
    incluir_texto: bool = True

async def processar_migracao_background(origem: str, destino: str, incluir_texto: bool):
    global estado_migracao

    estado_migracao.update({
        "em_andamento": True, "concluido": False, "erro_fatal": False,
        "total": 0, "processados": 0, "enviados": 0, "falhas": 0,
        "msg_atual": "Iniciando...", "msg_final": ""
    })

    app_pyro = obter_cliente_telegram()
    temp_dir = os.path.join(tempfile.gettempdir(), "tg_migra")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
    os.makedirs(temp_dir, exist_ok=True)

    try:
        async with app_pyro:
            canal_origem = await resolver_canal(app_pyro, origem)
            canal_destino = await resolver_canal(app_pyro, destino)

            # 1) Coleta TODAS as mensagens (mais novo -> mais antigo)
            estado_migracao["msg_atual"] = "Coletando mensagens do canal..."
            mensagens = [m async for m in app_pyro.get_chat_history(canal_origem)]

            # 2) Inverte para ordem cronológica (mais antigo primeiro)
            mensagens.reverse()
            estado_migracao["total"] = len(mensagens)

            # 3) Reenvia uma a uma
            for idx, msg in enumerate(mensagens):
                estado_migracao["processados"] = idx + 1
                caption = msg.caption or ""
                caminho = None

                try:
                    if msg.video or msg.animation or msg.document or msg.photo:
                        estado_migracao["msg_atual"] = f"Baixando mídia {idx+1}/{len(mensagens)}..."
                        ext = "mp4" if (msg.video or msg.animation) else "dat"
                        if msg.photo:
                            ext = "jpg"
                        caminho = os.path.join(temp_dir, f"m_{idx}.{ext}")

                        with open(caminho, "wb") as f:
                            async for chunk in app_pyro.stream_media(msg):
                                f.write(chunk)

                        estado_migracao["msg_atual"] = f"Enviando mídia {idx+1}/{len(mensagens)}..."
                        if msg.video:
                            await app_pyro.send_video(canal_destino, caminho, caption=caption)
                        elif msg.animation:
                            await app_pyro.send_animation(canal_destino, caminho, caption=caption)
                        elif msg.photo:
                            await app_pyro.send_photo(canal_destino, caminho, caption=caption)
                        else:
                            await app_pyro.send_document(canal_destino, caminho, caption=caption)

                        estado_migracao["enviados"] += 1

                    elif msg.text and incluir_texto:
                        estado_migracao["msg_atual"] = f"Enviando texto {idx+1}/{len(mensagens)}..."
                        await app_pyro.send_message(canal_destino, msg.text)
                        estado_migracao["enviados"] += 1

                except Exception as e_msg:
                    estado_migracao["falhas"] += 1
                    print(f"Falha na mensagem {idx}: {e_msg}")

                finally:
                    if caminho and os.path.exists(caminho):
                        os.remove(caminho)
                    gc.collect()
                    await asyncio.sleep(1)  # respeita rate limit do Telegram

        estado_migracao["msg_final"] = (
            f"Migração concluída! {estado_migracao['enviados']} enviados, "
            f"{estado_migracao['falhas']} falhas de {estado_migracao['total']}."
        )

    except Exception as e:
        estado_migracao["erro_fatal"] = True
        estado_migracao["msg_final"] = f"Erro fatal: {str(e)}"

    finally:
        estado_migracao["concluido"] = True
        estado_migracao["em_andamento"] = False
        shutil.rmtree(temp_dir, ignore_errors=True)
        gc.collect()

@app.get("/status_migracao")
def status_migracao():
    return estado_migracao

@app.post("/migrar")
async def migrar(payload: MigracaoPayload, background_tasks: BackgroundTasks):
    if estado_migracao["em_andamento"]:
        raise HTTPException(status_code=400, detail="Já existe uma migração em andamento.")
    background_tasks.add_task(
        processar_migracao_background,
        payload.origem, payload.destino, payload.incluir_texto
    )
    return {"status": "iniciado"}
