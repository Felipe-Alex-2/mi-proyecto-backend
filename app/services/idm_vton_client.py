"""
Cliente para el servicio IDM-VTON corriendo localmente con Gradio,
expuesto via ngrok. Usa gradio_client para comunicarse con la API
del modelo de virtual try-on.

Variables de entorno requeridas:
    VTON_URL: URL base de la app Gradio (ej. https://xxxx.ngrok-free.dev)
"""

import os
import tempfile
import urllib.request
from pathlib import Path

# gradio_client se importa lazy para no romper el arranque si no esta instalado
try:
    from gradio_client import Client, handle_file
    _GRADIO_AVAILABLE = True
except ImportError:
    _GRADIO_AVAILABLE = False

VTON_URL: str = os.getenv("VTON_URL", "").strip()

# Headers necesarios para saltar la advertencia del browser de ngrok
_NGROK_HEADERS = {"ngrok-skip-browser-warning": "true"}

# Timeout largo porque la inferencia del modelo puede tardar varios minutos
_TIMEOUT_SECONDS = 300


class IDMVTONUnavailableError(Exception):
    """Se lanza cuando el servicio VTON no esta disponible o no se pudo conectar."""


def _get_client() -> "Client":
    """Crea y retorna un cliente Gradio configurado con los headers de ngrok."""
    if not _GRADIO_AVAILABLE:
        raise IDMVTONUnavailableError(
            "gradio_client no esta instalado. Agrega 'gradio_client' a requirements.txt."
        )
    if not VTON_URL:
        raise IDMVTONUnavailableError(
            "La variable de entorno VTON_URL no esta configurada. "
            "Configurala en Railway con la URL del servicio ngrok."
        )
    try:
        client = Client(
            VTON_URL,
            headers=_NGROK_HEADERS,
        )
        return client
    except Exception as exc:
        raise IDMVTONUnavailableError(
            f"No se pudo conectar al servicio IDM-VTON en '{VTON_URL}': {exc}"
        ) from exc


def run_tryon(
    person_image_path: str,
    garment_image_path: str,
    garment_description: str = "",
    use_auto_mask: bool = True,
    use_auto_crop: bool = False,
    denoise_steps: int = 30,
    seed: int = 42,
) -> str:
    """
    Llama al endpoint /tryon del servicio IDM-VTON Gradio y retorna
    la ruta local del archivo de imagen resultante.
    """
    client = _get_client()

    # El primer parametro del endpoint /tryon es 'dict' (EditorData de Gradio):
    # un objeto con background (FileData), layers [], composite null.
    human_dict = {
        "background": handle_file(person_image_path),
        "layers": [],
        "composite": None,
    }

    result = client.predict(
        dict=human_dict,
        garm_img=handle_file(garment_image_path),
        garment_des=garment_description,
        is_checked=use_auto_mask,
        is_checked_crop=use_auto_crop,
        denoise_steps=float(denoise_steps),
        seed=float(seed),
        api_name="/tryon",
    )

    # El endpoint retorna (output_image_path, masked_image_path)
    if isinstance(result, (list, tuple)):
        output_path = result[0]
    else:
        output_path = result

    if isinstance(output_path, dict):
        output_path = output_path.get("path") or output_path.get("url", "")

    return str(output_path)


def run_tryon_from_bytes(
    person_image_bytes: bytes,
    person_filename: str,
    garment_image_bytes: bytes,
    garment_filename: str,
    garment_description: str = "",
    use_auto_mask: bool = True,
    use_auto_crop: bool = False,
    denoise_steps: int = 30,
    seed: int = 42,
) -> bytes:
    """
    Version de run_tryon que acepta bytes de imagen directamente.
    Guarda temporalmente los archivos, llama al servicio y retorna los bytes
    de la imagen resultado.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        person_path = Path(tmpdir) / person_filename
        person_path.write_bytes(person_image_bytes)

        garment_path = Path(tmpdir) / garment_filename
        garment_path.write_bytes(garment_image_bytes)

        output_path = run_tryon(
            person_image_path=str(person_path),
            garment_image_path=str(garment_path),
            garment_description=garment_description,
            use_auto_mask=use_auto_mask,
            use_auto_crop=use_auto_crop,
            denoise_steps=denoise_steps,
            seed=seed,
        )

        # Si el output es una URL, descargamos la imagen
        if output_path.startswith("http://") or output_path.startswith("https://"):
            req = urllib.request.Request(output_path, headers=_NGROK_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()

        # Si es una ruta local, leemos el archivo
        result_file = Path(output_path)
        if result_file.exists():
            return result_file.read_bytes()

        raise Exception(
            f"El servicio IDM-VTON retorno una ruta no accesible: {output_path}"
        )
