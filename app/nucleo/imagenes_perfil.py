import base64
import binascii
import io
import re
from PIL import Image, ImageOps, UnidentifiedImageError


def normalize_profile_photo(value: str | None) -> str | None:
    """Accept raster photos only, bound their size, and store a small JPEG."""
    if value is None:
        return None
    if not re.match(r'^data:image/(jpeg|png|webp);base64,', value):
        raise ValueError('Selecciona una foto JPG, PNG o WebP válida.')
    try:
        raw = base64.b64decode(value.split(',', 1)[1], validate=True)
        if len(raw) > 512 * 1024:
            raise ValueError('La foto debe ocupar como máximo 512 KB.')
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {'JPEG', 'PNG', 'WEBP'} or max(source.size) > 4096:
                raise ValueError('La foto debe ser JPG, PNG o WebP y medir como máximo 4096 px.')
            image = ImageOps.exif_transpose(source)
            image.thumbnail((512, 512))
            image = image.convert('RGBA')
            background = Image.new('RGB', image.size, '#FAF7F2')
            background.paste(image, mask=image.getchannel('A'))
            output = io.BytesIO()
            background.save(output, format='JPEG', quality=85, optimize=True)
        return 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode('ascii')
    except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('No se pudo leer la foto. Selecciona otra imagen.') from exc
