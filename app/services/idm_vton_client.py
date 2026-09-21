import io
import os
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image

try:
    from gradio_client import Client, handle_file
    _GRADIO_AVAILABLE = True
except ImportError:
    _GRADIO_AVAILABLE = False

VTON_URL: str = os.getenv("VTON_URL", "").strip()
_NGROK_HEADERS = {"ngrok-skip-browser-warning": "true"}
_MAX_SIZE = (768, 1024)


class IDMVTONUnavailableError(Exception):
    """Se lanza cuando el servicio VTON no esta disponible o no se pudo conectar."""


def _preprocess_image(image_bytes: bytes, filename: str):
    """Convierte a RGB, redimensiona hasta 768x1024 y guarda como JPEG."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception as exc:
        raise ValueError(f"No se pudo leer la imagen '{filename}': {exc}") from exc

    if img.mode != "RGB":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode in ("RGBA", "LA"):
            bg.paste(img, mask=img.split()[-1])
        else:
            bg.paste(img)
        img = bg

    if img.width > _MAX_SIZE[0] or img.height > _MAX_SIZE[1]:
        img.thumbnail(_MAX_SIZE, Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    stem = Path(filename).stem or "image"
    return buf.getvalue(), f"{stem}.jpg"


def _get_client():
    if not _GRADIO_AVAILABLE:
        raise IDMVTONUnavailableError("gradio_client no instalado.")
    if not VTON_URL:
        raise IDMVTONUnavailableError("VTON_URL no configurada en Railway.")
    try:
        return Client(VTON_URL, headers=_NGROK_HEADERS)
    except Exception as exc:
        raise IDMVTONUnavailableError(f"No se pudo conectar a IDM-VTON: {exc}") from exc


def run_tryon(person_image_path, garment_image_path, garment_description="",
              use_auto_mask=True, use_auto_crop=True, denoise_steps=30, seed=42):
    client = _get_client()
    human_dict = {"background": handle_file(person_image_path), "layers": [], "composite": None}
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
    if isinstance(result, (list, tuple)):
        output_path = result[0]
    else:
        output_path = result
    if isinstance(output_path, dict):
        output_path = output_path.get("path") or output_path.get("url", "")
    return str(output_path)


def run_tryon_from_bytes(person_image_bytes, person_filename, garment_image_bytes, garment_filename,
                         garment_description="", use_auto_mask=True, use_auto_crop=True,
                         denoise_steps=30, seed=42):
    person_bytes_clean, person_fn = _preprocess_image(person_image_bytes, person_filename)
    garment_bytes_clean, garment_fn = _preprocess_image(garment_image_bytes, garment_filename)

    with tempfile.TemporaryDirectory() as tmpdir:
        person_path = Path(tmpdir) / person_fn
        person_path.write_bytes(person_bytes_clean)
        garment_path = Path(tmpdir) / garment_fn
        garment_path.write_bytes(garment_bytes_clean)

        output_path = run_tryon(
            person_image_path=str(person_path),
            garment_image_path=str(garment_path),
            garment_description=garment_description,
            use_auto_mask=use_auto_mask,
            use_auto_crop=use_auto_crop,
            denoise_steps=denoise_steps,
            seed=seed,
        )

        if output_path.startswith("http://") or output_path.startswith("https://"):
            req = urllib.request.Request(output_path, headers=_NGROK_HEADERS)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()

        result_file = Path(output_path)
        if result_file.exists():
            return result_file.read_bytes()

        raise Exception(f"IDM-VTON retorno ruta no accesible: {output_path}")