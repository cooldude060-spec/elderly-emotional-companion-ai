from fastapi import FastAPI, Query
import sqlite3, os, queue, json, threading, requests
from dotenv import load_dotenv
from twilio.rest import Client
import pyttsx3, sounddevice as sd, vosk

load_dotenv()
app = FastAPI()

# --- Credentials ---
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE = os.getenv("TWILIO_PHONE")
MY_PHONE = os.getenv("MY_PHONE")

# --- Nebius Token Factory ---
NEBIUS_TOKEN = os.getenv("NEBIUS_TOKEN")
NANO_ENDPOINT = "https://api.nebius.ai/v1/nano"
ULTRA_ENDPOINT = "https://api.nebius.ai/v1/ultra"

def call_nemotron(model: str, prompt: str):
    endpoint = NANO_ENDPOINT if model == "nano" else ULTRA_ENDPOINT
    headers = {"Authorization": f"Bearer {NEBIUS_TOKEN}"}
    payload = {"input": prompt}
    resp = requests.post(endpoint, headers=headers, json=payload)
    return resp.json().get("output", "AI error")

# --- AI Reply with Model Switching ---
def generate_reply(context: str):
    if len(context.split()) < 6:  # short reminder → Nano
        return call_nemotron("nano", f"Empathetic reminder: {context}")
    else:  # complex reasoning → Ultra
        return call_nemotron("ultra", f"Reason about reminder: {context}")

# --- Voice System (Queue + Single Thread Loop) ---
engine = pyttsx3.init()
speech_queue = queue.Queue()

def speaker_loop():
    while True:
        text = speech_queue.get()
        if text is None:
            break
        if text.strip():
            print(f"Speaking: {text}")
            engine.say(text)
            engine.runAndWait()

threading.Thread(target=speaker_loop, daemon=True).start()

def speak(text: str):
    if text.strip():
        speech_queue.put(text)

# --- Voice Input ---
q = queue.Queue()
model_path = r"D:\\Study\\AI Projects\\elderly-companion\\elderly-companion\\vosk-model-small-hi-0.22"
model = vosk.Model(model_path)
rec = vosk.KaldiRecognizer(model, 16000)

def listen_voice(timeout=5):
    def callback(indata, frames, time, status):
        q.put(bytes(indata))
    with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype='int16',
                           channels=1, callback=callback):
        print("🎤 Bolna start karo...")
        sd.sleep(timeout * 1000)
        while not q.empty():
            data = q.get()
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = result.get("text", "")
                if text.strip():
                    return text
        return ""

# --- DB Init ---
def init_db():
    conn = sqlite3.connect("memory.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT
                )""")
    conn.commit()
    conn.close()
init_db()

# --- Add Reminder (Text + SMS/WhatsApp + Voice) ---
@app.post("/add_reminder/")
def add_reminder(reminder: str, enable_voice: bool = True):
    conn = sqlite3.connect("memory.db")
    c = conn.cursor()
    c.execute("INSERT INTO reminders (text) VALUES (?)", (reminder,))
    conn.commit()
    conn.close()

    ai_reply = generate_reply(reminder)
    if enable_voice:
        speak(ai_reply)

    # SMS/WhatsApp sending → offloaded to Nebius Serverless Job
    requests.post("https://api.nebius.ai/v1/jobs/send-reminder", json={"reminder": reminder})

    return {
        "message": "Reminder saved!",
        "ai_reply": ai_reply,
        "voice": f"Reminder spoken: {ai_reply}" if enable_voice else "Voice disabled"
    }

# --- Voice Add Reminder (NO SMS/WhatsApp) ---
@app.post("/voice_add_reminder/")
def voice_add_reminder(enable_voice: bool = True):
    user_input = listen_voice()
    if not user_input or user_input.strip() == "":
        ai_reply = "Mujhe samajh nahi aaya, dobara bolo."
        if enable_voice:
            speak(ai_reply)
        return {"error": "Voice not recognized", "ai_reply": ai_reply}

    conn = sqlite3.connect("memory.db")
    c = conn.cursor()
    c.execute("INSERT INTO reminders (text) VALUES (?)", (user_input,))
    conn.commit()
    conn.close()

    ai_reply = generate_reply(user_input)
    if enable_voice:
        speak(ai_reply)

    return {
        "message": "Reminder saved via voice!",
        "user_input": user_input,
        "ai_reply": ai_reply,
        "voice": f"Reminder spoken: {ai_reply}" if enable_voice else "Voice disabled"
    }

# --- Recall Reminders (Speak First Reminder) ---
@app.get("/recall_reminders/")
def recall_reminders(enable_voice: bool = True):
    conn = sqlite3.connect("memory.db")
    c = conn.cursor()
    c.execute("SELECT id, text FROM reminders")
    rows = [{"id": r[0], "text": r[1]} for r in c.fetchall()]
    conn.close()

    if enable_voice and rows:
        first_reply = generate_reply(rows[0]["text"])
        speak(first_reply)

    return {"reminders": rows}

# --- Search Reminders ---
@app.get("/search_reminders/")
def search_reminders(query: str = Query(...)):
    conn = sqlite3.connect("memory.db")
    c = conn.cursor()
    c.execute("SELECT id, text FROM reminders")
    rows = [{"id": r[0], "text": r[1]} for r in c.fetchall() if query.lower() in r[1].lower()]
    conn.close()
    return {"reminders": rows}

# --- Update Reminder ---
@app.put("/update_reminder/{reminder_id}")
def update_reminder(reminder_id: int, new_text: str):
    conn = sqlite3.connect("memory.db")
    c = conn.cursor()
    c.execute("UPDATE reminders SET text=? WHERE id=?", (new_text, reminder_id))
    conn.commit()
    conn.close()
    return {"message": f"Reminder {reminder_id} updated!"}

# --- Delete Reminder ---
@app.delete("/delete_reminder/{reminder_id}")
def delete_reminder(reminder_id: int):
    conn = sqlite3.connect("memory.db")
    c = conn.cursor()
    c.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
    conn.commit()
    conn.close()
    return {"message": f"Reminder {reminder_id} deleted!"}

# --- Voice AI Free Talk ---
@app.get("/voice_ai/")
def voice_ai(enable_voice: bool = True):
    user_input = listen_voice()
    if not user_input or user_input.strip() == "":
        ai_reply = "Mujhe samajh nahi aaya, dobara bolo."
        if enable_voice:
            speak(ai_reply)
        return {"error": "Voice not recognized", "ai_reply": ai_reply}

    ai_reply = generate_reply(user_input)
    if enable_voice:
        speak(ai_reply)

    return {"user_input": user_input, "ai_reply": ai_reply}
