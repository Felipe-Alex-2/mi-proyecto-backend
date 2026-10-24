"""Bundled municipality/capital names, independent of external services at runtime.

Source: Laboratorio de Tecnologías Sociales, CPV 2024, CC BY 4.0.
https://github.com/lab-tecnosocial/municipios-bolivia-2024
"""
import json
import unicodedata
from pathlib import Path
from fastapi import HTTPException

LOCATIONS = json.loads((Path(__file__).parents[1] / 'datos' / 'ubicaciones_bolivia.json').read_text(encoding='utf-8'))


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.strip())
                   if unicodedata.category(c) != 'Mn').casefold()


def department_name(value):
    match = next((name for name in LOCATIONS if normalized(name) == normalized(value)), None)
    if not match:
        raise ValueError('Selecciona uno de los nueve departamentos de Bolivia.')
    return match


def municipality_name(department, value):
    # Common short name for the departmental capital.
    if department == 'Santa Cruz' and normalized(value) == 'santa cruz':
        value = 'Santa Cruz de la Sierra'
    match = next((name for name in LOCATIONS[department] if normalized(name) == normalized(value)), None)
    if not match:
        raise HTTPException(422, f'Selecciona una ciudad/municipio del departamento de {department}.')
    return match
