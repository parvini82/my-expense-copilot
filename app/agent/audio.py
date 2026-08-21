import io
import logging
import os
from typing import Optional
from openai import AsyncOpenAI
from app.config import get_settings

logger = logging.getLogger("expense_agent.audio")


def get_whisper_client() -> AsyncOpenAI:
    """Initialize AsyncOpenAI client for Whisper audio transcription."""
    settings = get_settings()
    # Prioritize OPENAI_API_KEY, fallback to OPENROUTER_API_KEY if applicable
    api_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY") or settings.OPENROUTER_API_KEY
    base_url = None

    # If using OpenRouter or custom proxy for whisper
    if not settings.OPENAI_API_KEY and settings.OPENROUTER_API_KEY:
        base_url = settings.OPENROUTER_BASE_URL

    if not api_key:
        logger.warning("No API key configured for Whisper transcription. Set OPENAI_API_KEY in .env.")

    return AsyncOpenAI(api_key=api_key or "missing_key", base_url=base_url)


async def transcribe_voice_bytes(
    audio_bytes: bytes,
    filename: str = "voice.oga",
    language: Optional[str] = None,
) -> str:
    """Transcribe voice audio bytes into text using OpenAI Whisper API.

    Args:
        audio_bytes: Raw bytes of the voice audio file (e.g., Telegram OGA/OGG).
        filename: Synthetic filename with appropriate extension for MIME detection.
        language: Optional ISO-639-1 language code (e.g., 'en', 'es').

    Returns:
        str: Transcribed text from the audio.

    Raises:
        RuntimeError: If transcription fails or returns an empty response.
    """
    if not audio_bytes:
        raise ValueError("Audio bytes cannot be empty for transcription.")

    client = get_whisper_client()

    try:
        # Create an in-memory binary stream with the required name attribute
        audio_buffer = io.BytesIO(audio_bytes)
        audio_buffer.name = filename

        logger.info("Sending audio buffer (%d bytes) to Whisper API...", len(audio_bytes))

        kwargs = {
            "model": "whisper-1",
            "file": audio_buffer,
        }
        if language:
            kwargs["language"] = language

        transcript = await client.audio.transcriptions.create(**kwargs)
        transcribed_text = transcript.text.strip()

        logger.info("Whisper transcription completed: '%s'", transcribed_text)
        return transcribed_text

    except Exception as e:
        logger.error("Whisper transcription error: %s", e, exc_info=True)
        raise RuntimeError(f"Failed to transcribe voice audio: {str(e)}") from e
