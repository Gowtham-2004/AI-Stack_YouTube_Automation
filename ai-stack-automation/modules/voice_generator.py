"""Generate scene voiceover, with a Windows TTS fallback when remote TTS is unavailable."""

from __future__ import annotations

import logging
import subprocess
import wave
from pathlib import Path

from config.settings import Settings


LOGGER = logging.getLogger(__name__)
DEFAULT_SCENE_DURATION = 5.0
POWERSHELL_TTS_TEMPLATE = r"""
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.Rate = -1
$speaker.Volume = 100
$voice = $speaker.GetInstalledVoices() | ForEach-Object {{ $_.VoiceInfo }} | Where-Object {{ $_.Culture.Name -like 'en*' }} | Select-Object -First 1
if ($voice -ne $null) {{
  $speaker.SelectVoice($voice.Name)
}}
$speaker.SetOutputToWaveFile('{output_path}')
$speaker.Speak('{text}')
$speaker.Dispose()
""".strip()


def _write_silent_wave(output_path: Path, duration_seconds: float) -> None:
    """Create silence only if speech synthesis is unavailable."""
    sample_rate = 22_050
    frame_count = int(sample_rate * duration_seconds)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)


def _escape_powershell_single_quotes(value: str) -> str:
    return value.replace("'", "''")


def _normalize_narration(narration_text: str) -> str:
    cleaned = " ".join(narration_text.strip().split())
    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def _generate_voiceover_with_windows_tts(narration_text: str, output_path: Path) -> bool:
    """Use built-in Windows speech synthesis for an offline English voiceover."""
    command = POWERSHELL_TTS_TEMPLATE.format(
        output_path=_escape_powershell_single_quotes(str(output_path)),
        text=_escape_powershell_single_quotes(_normalize_narration(narration_text)),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if completed.stderr.strip():
            LOGGER.debug("Windows TTS stderr: %s", completed.stderr.strip())
        return output_path.exists() and output_path.stat().st_size > 0
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("Windows TTS fallback unavailable: %s", exc)
        return False


def generate_scene_audio(
    scene_number: int,
    narration_text: str,
    output_path: Path,
    settings: Settings,
) -> Path:
    """Generate one voiceover clip per scene."""
    if not narration_text.strip():
        raise ValueError("Narration text is empty.")

    generated = _generate_voiceover_with_windows_tts(
        narration_text=narration_text,
        output_path=output_path,
    )
    if not generated:
        _write_silent_wave(
            output_path=output_path,
            duration_seconds=DEFAULT_SCENE_DURATION,
        )
        LOGGER.info(
            "Scene %s audio generated as silence fallback because no voiceover engine was available for model %s.",
            scene_number,
            settings.magpie_tts_model,
        )
        return output_path

    LOGGER.info(
        "Scene %s voiceover generated with local Windows TTS fallback for model %s.",
        scene_number,
        settings.magpie_tts_model,
    )
    return output_path
