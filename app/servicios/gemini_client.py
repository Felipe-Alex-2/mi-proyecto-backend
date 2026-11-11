import time
from typing import Any, Dict

import httpx

from app.configuracion import settings
from app.nucleo.excepciones import SolicitudInvalidaException, ProveedorIAUnavailableException


class GeminiClient:
    RETRYABLE_STATUS_CODES = {429, 500, 503, 504, 529}

    @classmethod
    def generate_text(cls, prompt: str, *, json_mode: bool = False) -> str:
        if not settings.GEMINI_API_KEY:
            raise SolicitudInvalidaException(detail="GEMINI_API_KEY no está configurada en el backend")

        models = [settings.GEMINI_MODEL]
        if json_mode and settings.GEMINI_REPORT_FALLBACK_MODEL and settings.GEMINI_REPORT_FALLBACK_MODEL not in models:
            models.append(settings.GEMINI_REPORT_FALLBACK_MODEL)
        if settings.GEMINI_FALLBACK_MODEL and settings.GEMINI_FALLBACK_MODEL not in models:
            models.append(settings.GEMINI_FALLBACK_MODEL)

        last_error = "Gemini no pudo procesar la solicitud"
        for model_index, model in enumerate(models):
            for attempt in range(1 if json_mode else 2):
                try:
                    body={"contents": [{"parts": [{"text": prompt}]}]}
                    if json_mode:
                        config={"responseMimeType":"application/json","temperature":0.1,"maxOutputTokens":3072}
                        if model.startswith(('gemini-3.6','gemini-3.5','gemini-3-flash')):
                            config['thinkingConfig']={"thinkingLevel":"minimal"}
                        elif model.startswith(('gemini-3','gemini-4')):
                            config['thinkingConfig']={"thinkingLevel":"low"}
                        elif model in ('gemini-flash-latest','gemini-flash-lite-latest','gemini-pro-latest'):
                            config['thinkingConfig']={"thinkingLevel":"low"}
                        elif model.startswith('gemini-2.5-flash'):
                            config['thinkingConfig']={"thinkingBudget":0}
                        body['generationConfig']=config
                    response = httpx.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                        headers={"x-goog-api-key":settings.GEMINI_API_KEY},
                        json=body,
                        timeout=12.0 if json_mode else 30.0,
                    )
                    if response.status_code in cls.RETRYABLE_STATUS_CODES:
                        last_error = cls._error_message(response)
                        if attempt == 0 and not json_mode:
                            time.sleep(0.7)
                            continue
                        break
                    response.raise_for_status()
                    payload = response.json()
                    return payload["candidates"][0]["content"]["parts"][0]["text"]
                except httpx.HTTPStatusError as exc:
                    last_error = cls._error_message(exc.response)
                    if exc.response.status_code==404 and model_index<len(models)-1:
                        break
                    if exc.response.status_code not in cls.RETRYABLE_STATUS_CODES:
                        raise SolicitudInvalidaException(detail=f"Gemini rechazó la consulta: {last_error}") from exc
                    if attempt == 0 and not json_mode:
                        time.sleep(0.7)
                        continue
                    break
                except (KeyError, IndexError, TypeError) as exc:
                    raise SolicitudInvalidaException(
                        detail="Gemini devolvió una respuesta sin contenido interpretable"
                    ) from exc
                except httpx.RequestError as exc:
                    last_error = f"No se pudo conectar con Gemini: {exc}"
                    if attempt == 0 and not json_mode:
                        time.sleep(0.7)
                        continue
                    break

            if model_index < len(models) - 1:
                continue

        error_type=ProveedorIAUnavailableException if json_mode else SolicitudInvalidaException
        raise error_type(
            detail=(
                ("No se pudo completar la interpretación del reporte con el proveedor de IA. " if json_mode else "El asistente está recibiendo muchas solicitudes. ") +
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
