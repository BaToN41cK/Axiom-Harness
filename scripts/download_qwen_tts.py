"""Download Qwen3-TTS-12Hz-0.6B-Base into models/tts/ (download only, no TTS wiring)."""
from pathlib import Path
from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "models" / "tts" / "Qwen3-TTS-12Hz-0.6B-Base"

path = snapshot_download(
    repo_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    local_dir=str(TARGET),
)
print(f"downloaded to: {path}")
