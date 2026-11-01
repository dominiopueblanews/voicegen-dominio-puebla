import asyncio
import os
import sys
import json
import uuid
import time
import socket
from aiohttp import web
import edge_tts

PORT = int(os.environ.get("PORT", 8055))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "generated_audio")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Voces oficiales seleccionadas: México y Latino USA
PRESET_VOICES = [
    {
        "id": "es-US-AlonsoNeural",
        "name": "Locutor Alonso (Oficial Dominio Puebla)",
        "country": "Latino USA",
        "gender": "Hombre",
        "tag": "Ganador Oficial",
        "description": "Voz institucional comercial y enérgica. Calibrada con +30% de velocidad y +6Hz de tono.",
        "defaultRate": "+30%",
        "defaultPitch": "+6Hz"
    },
    {
        "id": "es-MX-JorgeNeural",
        "name": "Profesor Jorge",
        "country": "México",
        "gender": "Hombre",
        "tag": "El Profesor",
        "description": "Voz masculina cálida, pedagógica y clara. Ideal para explicaciones detalladas.",
        "defaultRate": "-4%",
        "defaultPitch": "-1Hz"
    },
    {
        "id": "es-US-PalomaNeural",
        "name": "Locutora Paloma",
        "country": "Latino USA",
        "gender": "Mujer",
        "tag": "Locutora Comercial",
        "description": "Voz femenina dinámica y moderna para anuncios, intros y contenido publicitario.",
        "defaultRate": "+15%",
        "defaultPitch": "+0Hz"
    },
    {
        "id": "es-MX-DaliaNeural",
        "name": "Profesora Dalia",
        "country": "México",
        "gender": "Mujer",
        "tag": "La Educadora",
        "description": "Voz femenina empática, articulada y profesional para tutoriales y capacitación.",
        "defaultRate": "+0%",
        "defaultPitch": "+0Hz"
    }
]

def get_local_ip():
    """Detecta la IP local de la máquina para conectar desde Android"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

@web.middleware
async def cors_middleware(request, handler):
    """Manejo nativo de CORS para permitir peticiones desde dominiopuebla.com.mx o local"""
    if request.method == "OPTIONS":
        response = web.Response(status=200)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as ex:
            response = ex
        except Exception as ex:
            response = web.json_response({"status": "error", "message": str(ex)}, status=500)
            
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    return response

async def handle_voices(request):
    """Devuelve las voces recomendadas y la lista filtrada a México y Latino USA"""
    try:
        all_voices = await edge_tts.list_voices()
        target_voices = [
            {
                "id": v["ShortName"],
                "name": v["ShortName"].replace("Neural", "").split("-")[-1],
                "locale": v["Locale"],
                "gender": "Hombre" if v.get("Gender", "").lower() == "male" else "Mujer",
                "country": "México" if "MX" in v["Locale"] else "Latino USA"
            }
            for v in all_voices
            if v.get("Locale", "").startswith("es-MX") or v.get("Locale", "").startswith("es-US")
        ]
        return web.json_response({
            "status": "success",
            "presets": PRESET_VOICES,
            "all_spanish": sorted(target_voices, key=lambda x: (x["country"], x["name"]))
        })
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

async def handle_generate(request):
    """Genera audio con Edge-TTS a partir de texto y parámetros"""
    try:
        data = await request.json()
        text = data.get("text", "").strip()
        voice = data.get("voice", "es-US-AlonsoNeural")
        rate = data.get("rate", "+30%")
        pitch = data.get("pitch", "+6Hz")
        volume = data.get("volume", "+0%")

        if not text:
            return web.json_response({"status": "error", "message": "El texto no puede estar vacío."}, status=400)

        # Generar nombre de archivo único
        file_id = f"audio_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp3"
        file_path = os.path.join(OUTPUT_DIR, file_id)

        # Ejecutar síntesis de voz neuronal
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            pitch=pitch,
            volume=volume
        )
        await communicate.save(file_path)

        file_size = os.path.getsize(file_path)

        return web.json_response({
            "status": "success",
            "file_id": file_id,
            "url": f"/api/audio/{file_id}",
            "size_kb": round(file_size / 1024, 2),
            "voice": voice,
            "text": text[:70] + ("..." if len(text) > 70 else "")
        })
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

async def handle_audio(request):
    """Sirve el archivo de audio MP3 generado con soporte de reproducción y descarga"""
    file_id = request.match_info.get("filename")
    file_path = os.path.join(OUTPUT_DIR, file_id)

    if not os.path.exists(file_path) or not file_id.endswith(".mp3"):
        raise web.HTTPNotFound(text="Audio no encontrado")

    return web.FileResponse(
        file_path,
        headers={
            "Content-Type": "audio/mpeg",
            "Content-Disposition": f'inline; filename="{file_id}"',
            "Cache-Control": "public, max-age=86400"
        }
    )

async def handle_index(request):
    """Sirve la interfaz web PWA principal"""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return web.FileResponse(index_path)
    return web.Response(text="Interfaz cargando...", content_type="text/html")

async def handle_info(request):
    """Devuelve la información de red del servidor para conexión móvil"""
    local_ip = get_local_ip()
    return web.json_response({
        "status": "success",
        "local_ip": local_ip,
        "port": PORT,
        "pc_url": f"http://localhost:{PORT}",
        "mobile_url": f"http://{local_ip}:{PORT}"
    })

def init_app():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/info", handle_info)
    app.router.add_get("/api/voices", handle_voices)
    app.router.add_post("/api/generate", handle_generate)
    app.router.add_get("/api/audio/{filename}", handle_audio)
    app.router.add_static("/static", STATIC_DIR)
    return app

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    local_ip = get_local_ip()
    print("=" * 65)
    print("[*] GENERADOR DE VOZ NEURONAL - DOMINIO PUEBLA")
    print("=" * 65)
    print(f"Windows 11 (PC local):  http://localhost:{PORT}")
    print(f"Android (Móvil Wi-Fi):  http://{local_ip}:{PORT}")
    print("=" * 65)
    print("Presiona Ctrl+C para detener el servidor.")
    print("=" * 65)

    app = init_app()
    web.run_app(app, host="0.0.0.0", port=PORT)
