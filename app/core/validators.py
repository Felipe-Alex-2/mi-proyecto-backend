import re
from typing import Optional


def validate_password_strength(password: str) -> str:
    """Valida que la contraseña cumpla los requisitos de seguridad:

    - Mínimo 8 caracteres
    - Al menos 1 letra mayúscula
    - Al menos 1 letra minúscula
    - Al menos 1 número
    - Al menos 1 símbolo especial
    """
    if not password or len(password) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")

    if not any(c.isupper() for c in password):
        raise ValueError("La contraseña debe contener al menos una letra mayúscula.")

    if not any(c.islower() for c in password):
        raise ValueError("La contraseña debe contener al menos una letra minúscula.")

    if not any(c.isdigit() for c in password):
        raise ValueError("La contraseña debe contener al menos un número.")

    # Símbolo: cualquier carácter que no sea alfanumérico ni espacio
    if not any(not c.isalnum() and not c.isspace() for c in password):
        raise ValueError("La contraseña debe contener al menos un símbolo especial (ej. !@#$%^&*).")

    return password


def validate_not_blank(value: Optional[str], field_name: str = "campo") -> Optional[str]:
    """Si el campo se envía (no es None), valida que no sea una cadena vacía o de solo espacios."""
    if value is not None:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"El {field_name} no puede estar vacío ni contener solo espacios.")
        return cleaned
    return value


def validate_required_string(value: str, field_name: str = "campo", min_len: int = 1) -> str:
    """Valida que un campo obligatorio tenga texto real tras eliminar espacios extremos."""
    if value is None:
        raise ValueError(f"El {field_name} es requerido.")
    cleaned = value.strip()
    if len(cleaned) < min_len:
        raise ValueError(f"El {field_name} debe tener al menos {min_len} caracter(es) válidos.")
    return cleaned
