"""Audio → Cantonese transcript.

Originally Google Cloud Speech-to-Text via partner branch; rewritten to use
Bailian DashScope `fun-asr` via the **native DashScope async transcription
API**. (`fun-asr` is NOT exposed through OpenAI-compat `audio.transcriptions`
— that endpoint returns 404 for `fun-asr`. The native async API
`/api/v1/services/audio/asr/transcription` only accepts `file_urls`, so we
upload the local recording to DashScope's temporary OSS via the SDK helper
`dashscope.utils.oss_utils.upload_file` first.)

Mock fallback: when `DASHSCOPE_API_KEY` is empty, returns the sample
transcript shipped from the partner branch tests folder so the demo
runs end-to-end without credentials.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from ...config import settings
from .errors import VisitNoteAgentError


def _patch_ssl_for_icloud() -> None:
    """Workaround: iCloud Drive 'Optimize Mac Storage' may evict certifi's
    cacert.pem (replace with a zero-byte stub), causing SSLEOFError on any
    outbound HTTPS from the requests / urllib3 stack.

    If REQUESTS_CA_BUNDLE / SSL_CERT_FILE are already set (e.g. by the
    /tmp/careflow_backend.sh launcher or Docker), this function is a no-op.
    Otherwise it scans well-known local cert paths and selects the first
    intact one (size > 50 KB = real PEM bundle).
    """
    if os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE"):
        return
    candidates = [
        "/opt/homebrew/etc/openssl@3/cert.pem",   # Homebrew (Apple Silicon)
        "/usr/local/etc/openssl@3/cert.pem",       # Homebrew (Intel)
        "/usr/local/etc/openssl/cert.pem",
        "/etc/ssl/cert.pem",                        # macOS system
        "/etc/ssl/certs/ca-certificates.crt",       # Linux / Docker
    ]
    for p in candidates:
        try:
            if os.path.getsize(p) > 50_000:
                os.environ["REQUESTS_CA_BUNDLE"] = p
                os.environ["SSL_CERT_FILE"] = p
                break
        except OSError:
            continue


class TranscriptionError(VisitNoteAgentError):
    pass


SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

_MOCK_TRANSCRIPT_FALLBACK = (
    "（mock 模式）社工：陳婆婆，你今日精神都唔錯喎。\n"
    "婆婆：仲可以啦，膝頭有啲痛，落樓梯就驚跌。\n"
    "社工：屋企有冇人陪你睇醫生？\n"
    "婆婆：個仔星期六先得閒，平時靠樓下嘅鄰居幫手買餸。\n"
    "社工：飲食、瞓眠點？\n"
    "婆婆：胃口麻麻，夜晚一二點先瞓得着，朝早五點就醒咗。\n"
    "社工：好，我哋安排物理治療師上門評估，再幫你睇下長者中心嘅日托。"
)


def transcribe_audio(audio_path: str) -> str:
    path = Path(audio_path)
    if not path.exists():
        raise TranscriptionError(f"Audio file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        raise TranscriptionError(
            f"Unsupported audio type: {path.suffix}. Supported: {sorted(SUPPORTED_AUDIO_EXTENSIONS)}"
        )

    # Mock mode — no DashScope ASR key.
    if settings.is_asr_mock:
        sample = _load_sample_transcript()
        return sample or _MOCK_TRANSCRIPT_FALLBACK

    # Patch SSL cert path before any DashScope HTTPS call — guards against
    # iCloud Drive evicting certifi's PEM bundle (SSLEOFError on OSS upload).
    _patch_ssl_for_icloud()

    try:
        import dashscope  # type: ignore
        from dashscope.utils.oss_utils import upload_file  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise TranscriptionError(
            "dashscope SDK not installed. Run `pip install 'dashscope>=1.20.0'`."
        ) from exc

    api_key = settings.dashscope_api_key
    model = settings.bailian_asr_model  # "fun-asr"
    dashscope.api_key = api_key

    # Step 1 — upload local file to DashScope temp OSS, get an oss:// URL.
    # (SDK helper returns oss://...; the Python `Transcription.async_call` cannot
    # consume oss:// URLs but the REST API can, via header X-DashScope-OssResourceResolve.)
    abs_path = str(path.resolve())
    try:
        file_url = upload_file(
            model=model,
            upload_path=f"file://{abs_path}",
            api_key=api_key,
        )
    except Exception as exc:  # noqa: BLE001
        raise TranscriptionError(f"DashScope OSS upload failed: {exc}") from exc
    if not file_url:
        raise TranscriptionError("DashScope OSS upload returned empty URL.")

    submit_url = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
        # Required so service backend can resolve oss:// temp URLs produced by SDK upload.
        "X-DashScope-OssResourceResolve": "enable",
    }
    submit_body = {
        "model": model,
        "input": {"file_urls": [file_url]},
        "parameters": {"language_hints": ["yue"]},  # Cantonese
    }

    # Step 2 — submit async transcription task (fun-asr).
    try:
        sr = requests.post(submit_url, headers=headers, json=submit_body, timeout=30)
        sr.raise_for_status()
        submit_payload = sr.json()
    except Exception as exc:  # noqa: BLE001
        raise TranscriptionError(f"ASR submit failed: {exc}") from exc

    task_id = (submit_payload.get("output") or {}).get("task_id")
    if not task_id:
        raise TranscriptionError(f"ASR submit returned no task_id; resp={submit_payload!r}")

    # Step 3 — poll until finished (fun-asr is fast; cap at ~5 min).
    import time
    task_url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
    query_headers = {"Authorization": f"Bearer {api_key}"}
    deadline = time.time() + 300
    final_payload: dict = {}
    while True:
        try:
            qr = requests.get(task_url, headers=query_headers, timeout=30)
            qr.raise_for_status()
            final_payload = qr.json()
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(f"ASR poll failed: {exc}") from exc
        status = ((final_payload.get("output") or {}).get("task_status")) or ""
        if status in {"SUCCEEDED", "FAILED", "UNKNOWN"}:
            break
        if time.time() > deadline:
            raise TranscriptionError(f"ASR poll timeout (>5min); last status={status}")
        time.sleep(2)

    output = final_payload.get("output") or {}
    if output.get("task_status") != "SUCCEEDED":
        raise TranscriptionError(
            f"ASR task not SUCCEEDED: status={output.get('task_status')}, "
            f"code={output.get('code')}, msg={output.get('message')}"
        )

    results = output.get("results") or []
    if not results:
        raise TranscriptionError(f"ASR returned no results; output={output!r}")
    first = results[0] if isinstance(results, list) else results
    subtask_status = first.get("subtask_status")
    transcription_url = first.get("transcription_url")
    if subtask_status != "SUCCEEDED" or not transcription_url:
        raise TranscriptionError(
            f"ASR subtask failed: status={subtask_status}, result={first!r}"
        )

    # Step 4 — fetch transcription JSON and extract text.
    try:
        r = requests.get(transcription_url, timeout=60)
        r.raise_for_status()
        payload = r.json()
    except Exception as exc:  # noqa: BLE001
        raise TranscriptionError(f"Fetch transcription JSON failed: {exc}") from exc

    text = _extract_text_from_transcription(payload).strip()
    if not text:
        raise TranscriptionError(
            "ASR returned empty transcript; raw payload (truncated): "
            f"{json.dumps(payload, ensure_ascii=False)[:400]}"
        )
    return text


def _extract_text_from_transcription(payload: dict) -> str:
    """DashScope transcription JSON → plain text.

    Schema: {"transcripts": [{"text": "...", "sentences": [{"text": "..."}]}]}
    """
    chunks: list[str] = []
    for t in payload.get("transcripts") or []:
        seg = (t.get("text") or "").strip()
        if seg:
            chunks.append(seg)
            continue
        for s in t.get("sentences") or []:
            stext = (s.get("text") or "").strip()
            if stext:
                chunks.append(stext)
    if not chunks:
        top = (payload.get("text") or "").strip()
        if top:
            chunks.append(top)
    return "\n".join(chunks)


def _load_sample_transcript() -> str | None:
    candidate = (
        Path(__file__).resolve().parents[3]
        / "tests" / "visit_note" / "transcript_example.txt"
    )
    if candidate.exists():
        return candidate.read_text(encoding="utf-8").strip()
    return None
