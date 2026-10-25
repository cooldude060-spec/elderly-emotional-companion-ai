"""
Elderly Emotional Companion — hackathon starter
FastAPI + SQLite + Nebius Token Factory Nemotron + optional voice/SMS.
"""
from __future__ import annotations

import os
import re
import json
import sqlite3
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    import sounddevice as sd
    import vosk
except ImportError:
    sd, vosk = None, None

try:
    from twilio.rest import Client
except ImportError:
    Client = None

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "memory.db")))

NEBIUS_TOKEN = os.getenv("NEBIUS_TOKEN", "").strip()
NEBIUS_ENDPOINT = os.getenv(
    "NEBIUS_ENDPOINT", "https://api.studio.nebius.com/v1/completions"
)
MODEL_NANO = os.getenv("NEBIUS_MODEL_NANO", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
MODEL_SUPER = os.getenv("NEBIUS_MODEL_SUPER", "nvidia/nemotron-3-super-120b-a12b")
MODEL_ULTRA = os.getenv("NEBIUS_MODEL_ULTRA", "nvidia/Nemotron-3-Ultra-550b-a55b")
AI_TIMEOUT = int(os.getenv("NEBIUS_TIMEOUT_SECONDS", "30"))

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE = os.getenv("TWILIO_PHONE", "")
MY_PHONE = os.getenv("MY_PHONE", "")
SMS_ENABLED = os.getenv("SMS_ENABLED", "false").lower() == "true"

VOSK_MODEL_PATH = Path(os.getenv("VOSK_MODEL_PATH", str(BASE_DIR / "vosk-model-small-hi-0.22")))

app = FastAPI(title="Elderly Emotional Companion", version="2.0.0")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")
    
speech_queue: queue.Queue = queue.Queue()
speech_engine = None
voice_model = None
voice_recognizer = None

# ---------- Database ----------
def get_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                due_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
        """)
        # Upgrade an existing database created by the previous version.
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(reminders)").fetchall()}
        if "due_at" not in columns:
            conn.execute("ALTER TABLE reminders ADD COLUMN due_at TEXT")
        if "status" not in columns:
            conn.execute("ALTER TABLE reminders ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'")
        if "created_at" not in columns:
            conn.execute("ALTER TABLE reminders ADD COLUMN created_at TEXT")
            conn.execute("UPDATE reminders SET created_at = ? WHERE created_at IS NULL",
                         (datetime.now(timezone.utc).isoformat(),))

init_db()

def save_reminder(text: str, due_at: Optional[str] = None) -> int:
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Reminder cannot be empty.")
    parsed_due = None
    if due_at:
        try:
            dt = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                # Naive ISO values are interpreted in the machine's local timezone.
                dt = dt.astimezone()
            parsed_due = dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            raise HTTPException(status_code=400, detail="due_at must be ISO 8601, e.g. 2026-10-23T22:00:00+05:30")
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO reminders(text, due_at, status, created_at) VALUES (?, ?, 'pending', ?)",
            (text, parsed_due, datetime.now(timezone.utc).isoformat())
        )
        return int(cur.lastrowid)

def fetch_reminders():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, text, due_at, status, created_at FROM reminders ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]

# ---------- Nemotron / Token Factory ----------
def choose_model(task: str) -> tuple[str, str]:
    """Simple requests use Nano; multi-step/ambiguous requests use Super/Ultra."""
    t = task.lower()
    ultra_terms = ("compare options", "multi-step", "complex plan", "reason through",
                   "several conditions", "analyze", "analyse", "why did", "what should i do")
    super_terms = ("summarize", "summarise", "organize", "organise", "plan my week",
                   "prioritize", "prioritise", "multiple tasks", "explain")
    if any(term in t for term in ultra_terms):
        return "ultra", MODEL_ULTRA
    if any(term in t for term in super_terms):
        return "super", MODEL_SUPER
    return "nano", MODEL_NANO

def call_nemotron(task: str, prompt: str, force_tier: Optional[str] = None) -> dict:
    if not NEBIUS_TOKEN:
        return {"ok": False, "reply": "AI unavailable: add NEBIUS_TOKEN to your .env file.",
                "model_tier": None, "model": None}
    if force_tier:
        tier = force_tier.lower()
        models = {"nano": MODEL_NANO, "super": MODEL_SUPER, "ultra": MODEL_ULTRA}
        if tier not in models:
            raise HTTPException(status_code=400, detail="model_tier must be nano, super, or ultra")
        model = models[tier]
    else:
        tier, model = choose_model(task)

    headers = {"Authorization": f"Bearer {NEBIUS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "prompt": prompt,
        "parameters": {"max_tokens": 160, "temperature": 0.2}
    }
    try:
        response = requests.post(NEBIUS_ENDPOINT, headers=headers, json=payload, timeout=AI_TIMEOUT)
        if not response.ok:
            # Model IDs can vary by Token Factory project/region; preserve diagnostic details.
            detail = response.text[:600]
            print(f"NEBIUS ERROR {response.status_code} model={model}: {detail}")
            return {"ok": False, "reply": "AI is temporarily unavailable. Your reminder is still saved.",
                    "model_tier": tier, "model": model, "error": detail}
        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            return {"ok": False, "reply": "AI returned no text. Your reminder is still saved.",
                    "model_tier": tier, "model": model}
        reply = choices[0].get("text", "")
        if not reply and isinstance(choices[0].get("message"), dict):
            reply = choices[0]["message"].get("content", "")
        reply = re.sub(r"(?s)^.*?</think>\s*", "", reply).strip()
        return {"ok": bool(reply), "reply": reply or "I saved your reminder.",
                "model_tier": tier, "model": model}
    except requests.RequestException as exc:
        print("NEBIUS REQUEST ERROR:", repr(exc))
        return {"ok": False, "reply": "AI is temporarily unavailable. Your reminder is still saved.",
                "model_tier": tier, "model": model, "error": str(exc)}

def generate_reply(reminder: str) -> dict:
    prompt = (
        "You are a kind, concise assistant for older adults. Rewrite the user's reminder "
        "as one short, clear, polite sentence. Do not add facts. Preserve names, numbers, "
        "amounts and times. If unsure, repeat the original reminder. Use simple English.\n"
        f"Original reminder (authoritative; do not change its facts): {reminder}\n"
        "Friendly reminder:"
    )
    return call_nemotron(reminder, prompt)


# ---------- Transcript-based wellbeing cues (not a medical diagnosis) ----------
def analyze_wellbeing(text: str) -> dict:
    """
    Use the configured Nebius text model to identify tentative emotional cues
    and explicit, self-reported pain information. Transcript only: no acoustic
    pitch/tone analysis and no clinical inference.
    """
    clean_text = text.strip()
    if not clean_text:
        return {
            "emotion": "unknown", "emotion_cues": [], "confidence": "low",
            "pain_reported": False, "self_reported_pain_level": None,
            "follow_up_question": "How are you feeling right now?",
            "supportive_response": "I'm here to listen.",
            "safety_note": "This is not a medical assessment."
        }

    prompt = (
        "You are a cautious wellbeing companion for older adults. Analyze ONLY the "
        "literal words in the user's transcript. Do not diagnose mental or physical "
        "conditions. Do not infer pain severity from emotion, word choice, or voice "
        "tone. Pain level must be a number from 0 to 10 ONLY when the user explicitly "
        "self-reports a number; otherwise null. If pain is mentioned without a number, "
        "ask what number from 0 (no pain) to 10 (worst pain) they would give it. "
        "Emotion is a tentative cue, not a fact. Use confidence low/medium/high as "
        "a rough model estimate, not a calibrated probability. If uncertain, use "
        "'unclear' and low. Never suggest or change medication doses or timing. "
        "Follow-up questions must be relevant to the user's actual concern. "
        "If pain is mentioned and a 0-10 score is available, acknowledge the score "
        "and ask one useful, non-diagnostic question. Prefer asking when the pain "
        "started or whether it is new, persistent, or worsening. Ask about daily "
        "activities only when relevant. Do not repeatedly ask for a pain score "
        "if the user has already provided one. Ask only one question at a time. "
        "Do not diagnose or recommend medication changes. "
        "Return ONLY valid JSON with exactly these keys: "
        '{"emotion":"calm|happy|sad|lonely|anxious|frustrated|unclear",'
        '"emotion_cues":["short phrase"],"confidence":"low|medium|high",'
        '"pain_reported":true,"self_reported_pain_level":null,'
        '"follow_up_question":"short question or empty string",'
        '"supportive_response":"one empathetic sentence",'
        '"safety_note":"brief safety note or empty string"}. '
        "If the transcript describes possible emergency symptoms such as chest pain, "
        "severe trouble breathing, stroke signs, collapse, or sudden severe pain, the "
        "supportive response must advise contacting local emergency services immediately. "
        "For pain_reported, true only if the person explicitly mentions physical pain. "
        "For self_reported_pain_level, use integer 0-10 only if explicitly stated "
        "by the user, otherwise null. Do not treat reminder times or medicine numbers "
        "as pain scores.\nTranscript: " + json.dumps(clean_text, ensure_ascii=False)
    )
    result = call_nemotron(
        "wellbeing emotion pain transcript cues",
        prompt,
        force_tier="nano"
    )
    fallback = {
        "emotion": "unclear",
        "emotion_cues": [],
        "confidence": "low",
        "pain_reported": bool(re.search(r"\b(pain|hurt|aching|ache|दर्द|दुख रहा|दर्द हो)\b", clean_text, re.I)),
        "self_reported_pain_level": None,
        "follow_up_question": "Are you in any physical pain? If yes, what number from 0 to 10 best describes it?",
        "supportive_response": "Thank you for telling me. I'm here to listen.",
        "safety_note": "These are tentative text cues, not a diagnosis."
    }
    try:
        raw = result.get("reply", "")
        # Tolerate fenced JSON and leading/trailing model commentary.
        raw = re.sub(r"(?s)^.*?```(?:json)?\s*", "", raw).strip()
        raw = re.sub(r"\s*```.*$", "", raw).strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end + 1])
            allowed_emotions = {"calm", "happy", "sad", "lonely", "anxious", "frustrated", "unclear"}
            emotion = parsed.get("emotion")
            if emotion not in allowed_emotions:
                emotion = "unclear"
            confidence = parsed.get("confidence")
            if confidence not in {"low", "medium", "high"}:
                confidence = "low"
            pain_level = parsed.get("self_reported_pain_level")
            # Accept only an explicit numeric self-report found in the transcript.
            explicit_score = re.search(
                r"(?:pain|दर्द)[^\d]{0,45}(10|[0-9])\s*(?:/|out of)\s*10|"
                r"(?:level|score|rating)[^\d]{0,15}(10|[0-9])\s*(?:/|out of)\s*10",
                clean_text, re.I
            )
            if not explicit_score or not isinstance(pain_level, int) or not 0 <= pain_level <= 10:
                pain_level = None
            return {
                "emotion": emotion,
                "emotion_cues": parsed.get("emotion_cues", []) if isinstance(parsed.get("emotion_cues", []), list) else [],
                "confidence": confidence,
                "pain_reported": bool(parsed.get("pain_reported", fallback["pain_reported"])),
                "self_reported_pain_level": pain_level,
                "follow_up_question": str(parsed.get("follow_up_question", fallback["follow_up_question"]))[:300],
                "supportive_response": str(parsed.get("supportive_response", fallback["supportive_response"]))[:500],
                "safety_note": "Tentative text-based cues only; not a diagnosis."
            }
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    # Safe fallback when the model is unavailable or doesn't return valid JSON.
    return fallback

class WellbeingRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)

# ---------- Optional text-to-speech ----------
if pyttsx3:
    try:
        speech_engine = pyttsx3.init()
    except Exception as exc:
        print("TTS INIT ERROR:", repr(exc))
        speech_engine = None

def speaker_loop():
    while True:
        text = speech_queue.get()
        try:
            if text is None:
                return
            if speech_engine and text.strip():
                speech_engine.say(text)
                speech_engine.runAndWait()
        except Exception as exc:
            print("TTS ERROR:", repr(exc))
        finally:
            speech_queue.task_done()

if speech_engine:
    threading.Thread(target=speaker_loop, daemon=True).start()

def speak(text: str):
    if speech_engine and text:
        speech_queue.put(text)

# ---------- Optional voice input ----------
if vosk and sd:
    try:
        if VOSK_MODEL_PATH.is_dir():
            voice_model = vosk.Model(str(VOSK_MODEL_PATH))
            voice_recognizer = vosk.KaldiRecognizer(voice_model, 16000)
        else:
            print("VOSK MODEL FOLDER NOT FOUND:", VOSK_MODEL_PATH)
    except Exception as exc:
        print("VOSK INIT ERROR:", repr(exc))

def listen_voice(seconds: int = 5) -> str:
    if not sd or not voice_recognizer:
        raise RuntimeError("Voice input unavailable. Check Vosk model folder, dependencies and microphone permission.")
    audio_q = queue.Queue()
    def callback(indata, frames, time_info, status):
        audio_q.put(bytes(indata))
    with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype="int16",
                           channels=1, callback=callback):
        print(f"Microphone active for {seconds} seconds. Speak now...")
        sd.sleep(seconds * 1000)
    parts = []
    while not audio_q.empty():
        chunk = audio_q.get()
        if voice_recognizer.AcceptWaveform(chunk):
            value = json.loads(voice_recognizer.Result()).get("text", "").strip()
            if value:
                parts.append(value)
    value = json.loads(voice_recognizer.FinalResult()).get("text", "").strip()
    if value:
        parts.append(value)
    return " ".join(parts).strip()

# ---------- Optional SMS ----------
def send_sms(message: str) -> dict:
    if not SMS_ENABLED:
        return {"sent": False, "reason": "SMS_ENABLED=false; SMS is disabled."}
    missing = [name for name, val in {
        "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID, "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
        "TWILIO_PHONE": TWILIO_PHONE, "MY_PHONE": MY_PHONE
    }.items() if not val]
    if missing:
        return {"sent": False, "reason": "Missing .env settings: " + ", ".join(missing)}
    if Client is None:
        return {"sent": False, "reason": "Twilio package is not installed."}
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        result = client.messages.create(body=message, from_=TWILIO_PHONE, to=MY_PHONE)
        return {"sent": True, "status": result.status, "sid": result.sid}
    except Exception as exc:
        code = getattr(exc, "code", None)
        msg = getattr(exc, "msg", None) or str(exc)
        print("TWILIO ERROR:", repr(exc))
        hint = ""
        if code == 57206 or "Invalid template name" in msg:
            hint = (" Twilio trial account is rejecting custom SMS text. Do not put a template name "
                    "in the body; verify the current Twilio trial/template rules or upgrade the account.")
        return {"sent": False, "error_code": code, "reason": msg + hint}

# ---------- API schemas ----------
class ReminderRequest(BaseModel):
    reminder: str = Field(min_length=1, max_length=1000)
    # ISO 8601 with timezone recommended, e.g. 2026-10-23T22:00:00+05:30
    due_at: Optional[str] = None
    enable_voice: bool = False
    enable_sms: bool = False

class AIRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    model_tier: Optional[str] = None

def notify_due_reminder(reminder: dict):
    # The original SQLite text is used for notification, never the AI paraphrase.
    message = f"Reminder: {reminder['text']}"
    speak(message)
    send_sms(message)

def scheduler_loop():
    """Poll due reminders. Mark notified before sending to avoid repeated sends on every poll."""
    while True:
        try:
            now = datetime.now(timezone.utc).isoformat()
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT id, text, due_at FROM reminders "
                    "WHERE status='pending' AND due_at IS NOT NULL AND due_at <= ?",
                    (now,)
                ).fetchall()
                for row in rows:
                    changed = conn.execute(
                        "UPDATE reminders SET status='notified' WHERE id=? AND status='pending'",
                        (row["id"],)
                    ).rowcount
                    if changed:
                        notify_due_reminder(dict(row))
        except Exception as exc:
            print("SCHEDULER ERROR:", repr(exc))
        time.sleep(15)

@app.on_event("startup")
def start_scheduler():
    threading.Thread(target=scheduler_loop, daemon=True, name="reminder-scheduler").start()

@app.post("/add_reminder/")
def add_reminder(payload: ReminderRequest):
    reminder_id = save_reminder(payload.reminder, payload.due_at)
    ai = generate_reply(payload.reminder)
    wellbeing = analyze_wellbeing(payload.reminder)
    if payload.enable_voice:
        speak(f"Reminder saved. {ai['reply']}")
    sms_result = send_sms(f"Elderly Companion reminder: {payload.reminder}") if payload.enable_sms else None
    return {
        "message": "Reminder saved!",
        "reminder_id": reminder_id,
        "reminder": payload.reminder,
        "due_at": payload.due_at,
        "status": "pending",
        "ai_reply": ai["reply"],
        "wellbeing": wellbeing,
        "ai_ok": ai["ok"],
        "model_tier": ai["model_tier"],
        "model": ai["model"],
        "voice_enabled": payload.enable_voice,
        "sms": sms_result
    }

@app.get("/recall_reminders/")
def recall_reminders():
    return {"reminders": fetch_reminders()}

@app.get("/search_reminders/")
def search_reminders(query: str = Query(..., min_length=1)):
    return {"reminders": [r for r in fetch_reminders() if query.lower() in r["text"].lower()]}

@app.put("/update_reminder/{reminder_id}")
def update_reminder(reminder_id: int, new_text: str = Query(..., min_length=1),
                    due_at: Optional[str] = None):
    # Validate/update due_at via a temporary row-safe parser.
    new_text = new_text.strip()
    if not new_text:
        raise HTTPException(status_code=400, detail="Reminder cannot be empty.")
    parsed_due = None
    if due_at:
        try:
            dt = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.astimezone()
            parsed_due = dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            raise HTTPException(status_code=400, detail="due_at must be ISO 8601.")
    with get_connection() as conn:
        if due_at is None:
            cur = conn.execute("UPDATE reminders SET text=?, status='pending' WHERE id=?", (new_text, reminder_id))
        else:
            cur = conn.execute("UPDATE reminders SET text=?, due_at=?, status='pending' WHERE id=?",
                               (new_text, parsed_due, reminder_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Reminder not found.")
    return {"message": "Reminder updated", "reminder_id": reminder_id, "new_text": new_text, "due_at": due_at}

@app.delete("/delete_reminder/{reminder_id}")
def delete_reminder(reminder_id: int):
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Reminder not found.")
    return {"message": f"Reminder {reminder_id} deleted"}

@app.post("/wellbeing_analyze/")
def wellbeing_analyze(payload: WellbeingRequest):
    return {"wellbeing": analyze_wellbeing(payload.text)}


@app.post("/ai_reply/")
def ai_reply(payload: AIRequest):
    result = call_nemotron(
        payload.text,
        "You are a helpful, kind assistant for older adults. Answer briefly and clearly. "
        "Do not invent personal or medical facts. Never invent medication dosage or timing. "
        "If this is a medical emergency, advise contacting local emergency services.\\n"
        f"User: {payload.text}\\nAssistant:",
        force_tier=payload.model_tier
    )
    result["wellbeing"] = analyze_wellbeing(payload.text)
    return result

@app.post("/voice_add_reminder/")
def voice_add_reminder(enable_voice: bool = False, enable_sms: bool = False,
                       due_at: Optional[str] = None):
    try:
        text = listen_voice()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Voice input unavailable: {exc}")
    if not text:
        return {"error": "Voice not recognized", "message": "Please try speaking again."}
    reminder_id = save_reminder(text, due_at)
    ai = generate_reply(text)
    wellbeing = analyze_wellbeing(text)
    if enable_voice:
        speech_text = f"Reminder saved. {ai['reply']}"
        speak(speech_text)
    sms_result = send_sms(f"Elderly Companion reminder: {text}") if enable_sms else None
    return {"message": "Reminder saved via voice", "reminder_id": reminder_id,
            "user_input": text, "due_at": due_at, "ai_reply": ai["reply"],
            "wellbeing": wellbeing, "model_tier": ai["model_tier"], "sms": sms_result}

@app.get("/")
def home():
    return {
        "message": "Elderly Emotional Companion API is running",
        "database": "ready",
        "nebius_configured": bool(NEBIUS_TOKEN),
        "models": {"nano": MODEL_NANO, "super": MODEL_SUPER, "ultra": MODEL_ULTRA},
        "sms_enabled": SMS_ENABLED,
        "voice_input_available": voice_recognizer is not None,
        "voice_output_available": speech_engine is not None,
        "scheduler": "background polling every 15 seconds"
    }
