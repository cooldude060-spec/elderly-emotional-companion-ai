from fastapi import FastAPI
from fastapi import Query
import requests
import sqlite3
import os 
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY")
USER_ID = os.getenv("USER_ID")
ORG_ID = os.getenv("ORG_ID")

app = FastAPI()

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

def send_sms(reminder: str):
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE")
    to_number = os.getenv("MY_PHONE")

    client = Client(account_sid, auth_token)

    message = client.messages.create(
        body=f"🔔 Reminder: {reminder}",
        from_=from_number,
        to=to_number
    )
    return message.sid

def send_whatsapp(reminder: str):
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = "whatsapp:" + os.getenv("TWILIO_PHONE")
    to_number = "whatsapp:" + os.getenv("MY_PHONE")

    client = Client(account_sid, auth_token)

    message = client.messages.create(
        body=f"🔔 Reminder: {reminder}",
        from_=from_number,
        to=to_number
    )
    return message.sid

@app.post("/add_reminder/")
def add_reminder(reminder: str):
    conn = sqlite3.connect("memory.db")
    c = conn.cursor()
    c.execute("INSERT INTO reminders (text) VALUES (?)", (reminder,))
    conn.commit()
    conn.close()
    #return {"message": "Reminder saved successfully!"}
    # Send SMS + WhatsApp
    sms_id = send_sms(reminder)
    wa_id = send_whatsapp(reminder)
    return {
        "message": "Reminder saved successfully!",
        "sms_id": sms_id,
        "whatsapp_id": wa_id
    }

@app.get("/recall_reminders/")
def recall_reminders():
    conn = sqlite3.connect("memory.db")
    c = conn.cursor()
    c.execute("SELECT text FROM reminders")
    rows = c.fetchall()
    conn.close()
    reminders = [row[0] for row in rows]
    return {"reminders": reminders}

@app.get("/search_reminders/")
def search_reminders(query: str = Query(...)):
    conn = sqlite3.connect("memory.db")
    c = conn.cursor()
    c.execute("SELECT text FROM reminders")
    rows = c.fetchall()
    conn.close()
    # Retrieval: reminders fetch
    relevant = [row[0] for row in rows if query.lower() in row[0].lower()]
    # Augmentation: merge query + reminders
    context = f"User asked: {query}\nRelevant reminders:\n" + "\n".join(relevant)
    return {"context": context}

def generate_reply(context: str):
    url = "https://api.studio.nebius.ai/v1/completions"
    
    # Strict prompt template
    prompt_template = (
        f"User query: {context}\n"
        "Instruction: Reply ONLY with one short empathetic reminder sentence. "
        "Do not ask questions. Do not explain. Do not add extra text. "
        "Output must be a single line reminder."
        )   
    
    payload = {
        "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",   # ✅ exact model from Nebius dashboard
        "prompt": prompt_template,
        "parameters": {
            "max_tokens": 50,
            "temperature": 0.3   # ✅ lower randomness
        }
    }
    
    headers = {
        "Authorization": f"Bearer {NEBIUS_API_KEY}",
        "X-User-Id": USER_ID,
        "X-Org-Id": ORG_ID,
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        data = response.json()
        if "choices" in data and len(data["choices"]) > 0:
            reply = data["choices"][0].get("text", "").strip()
            # remove hidden reasoning markers if present
            if "</think>" in reply:
                reply = reply.split("</think>")[-1].strip()
            return reply
        else:
            return "No reply generated"
    else:
        return f"Error: {response.text}"

@app.get("/ai_reply/")
def ai_reply(query: str = Query(...)):
    conn = sqlite3.connect("memory.db")
    c = conn.cursor()

    # Query ke words se reminder dhoondho
    words = [
        word.strip(".,?!").lower()
        for word in query.split()
        if len(word.strip(".,?!")) > 2
    ]

    c.execute("SELECT text FROM reminders ORDER BY id DESC")
    reminders = [row[0] for row in c.fetchall()]
    conn.close()

    # Sabse zyada matching words wala reminder select karo
    best_reminder = None
    best_score = 0

    for reminder in reminders:
        reminder_lower = reminder.lower()
        score = sum(1 for word in words if word in reminder_lower)

        if score > best_score:
            best_score = score
            best_reminder = reminder

    if not best_reminder:
        return {
            "reply": "Sir, mujhe is baare mein koi saved reminder nahi mil raha."
        }

    # Friendly reminder wording
    reply = f"Please don't forget, beta: {best_reminder}."

    return {
        #"matched_reminder": best_reminder,
        "reply": reply
    }
    
#@app.get("/ai_reply/")
#def ai_reply(query: str = Query(...)):
   # conn = sqlite3.connect("memory.db")
   # c = conn.cursor()
   # c.execute("SELECT text FROM reminders")
   # rows = c.fetchall()
   # conn.close()
  #  relevant = [row[0] for row in rows if query.lower() in row[0].lower()]
  #  context = f"User asked: {query}\nRelevant reminders:\n" + "\n".join(relevant)
  #  reply = generate_reply(context)
  #  return {"reply": reply}