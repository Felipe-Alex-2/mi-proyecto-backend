import time
from typing import Any, Dict

import httpx

from app.config import settings
from app.core.exceptions import BadRequestException


class GeminiClient:
    RETRYABLE_STATUS_CODES = {429, 500, 503, 504, 529}

    @classmethod
    def generate_text(cls, prompt: str) -> str:
        if not settings.GEMINI_API_KEY:
            raise BadRequestException(detail="GEMINI_API_KEY no está configurada en el backend")

        models = [settings.GEMINI_MODEL]
        if settings.GEMINI_FALLBACK_MODEL and settings.GEMINI_FALLBACK_MODEL not in models:
            models.append(settings.GEMINI_FALLBACK_MODEL)

        last_error = "Gemini no pudo procesar la solicitud"
        for model_index, model in enumerate(models):
            for attempt in range(2):
                try:
                    response = httpx.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                        params={"key": settings.GEMINI_API_KEY},
                        json={"contents": [{"parts": [{"text": prompt}]}]},
                        timeout=30.0,
                    )
                    if response.status_code in cls.RETRYABLE_STATUS_CODES:
                        last_error = cls._error_message(response)
                        if attempt == 0:
                            time.sleep(0.7)
                            continue
                        break
                    response.raise_for_status()
                    payload = response.json()
                    return payload["candidates"][0]["content"]["parts"][0]["text"]
                except httpx.HTTPStatusError as exc:
                    last_error = cls._error_message(exc.response)
                    if exc.response.status_code not in cls.RETRYABLE_STATUS_CODES:
                        raise BadRequestException(detail=f"Gemini rechazó la consulta: {last_error}") from exc
                    if attempt == 0:
                        time.sleep(0.7)
                        continue
                    break
                except (KeyError, IndexError, TypeError) as exc:
                    raise BadRequestException(
                        detail="Gemini devolvió una respuesta sin contenido interpretable"
                    ) from exc
                except httpx.RequestError as exc:
                    last_error = f"No se pudo conectar con Gemini: {exc}"
                    if attempt == 0:
                        time.sleep(0.7)
                        continue
                    break

            if model_index < len(models) - 1:
                continue

        raise BadRequestException(
            detail=(
                "El asistente está recibiendo muchas solicitudes. "
                "Intenta nuevamente en unos segundos. "
                f"Detalle técnico: {last_error}"
            )
        )

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            return response.json().get("error", {}).get("message", response.text)
        except ValueError:
            return response.text or f"HTTP {response.status_code}"
