Elderly Emotional Companion — wellbeing-aware update

Files:
- main.py: FastAPI backend with Nebius-based transcript wellbeing analysis.
- static/index.html: English dashboard with Health & Wellness check-in.
- requirements.txt: cleaned Python dependencies.

Install (Windows PowerShell, from this folder):
  py -m venv .venv
  .\.venv\Scripts\Activate.ps1
  python -m pip install --upgrade pip
  pip install -r requirements.txt

Create a .env file next to main.py:
  NEBIUS_TOKEN=your_token_here
  # Optional: keep the endpoint/model values already used in your project if your account requires them.
  # NEBIUS_ENDPOINT=https://api.studio.nebius.com/v1/completions

Run:
  uvicorn main:app --reload

Open:
  http://127.0.0.1:8000/dashboard
  http://127.0.0.1:8000/docs

New endpoint:
  POST /wellbeing_analyze/
  JSON body: {"text":"I feel lonely today and my knee hurts"}

The dashboard Health & Wellness page calls this endpoint. Reminder creation and /ai_reply/
also return a `wellbeing` object. Analysis is based on transcript text, not audio pitch or tone.
The model output is tentative and not clinically validated. A pain score is only accepted
when the user explicitly reports a score out of 10. If pain is mentioned without a score,
the companion asks a follow-up question. This is not a medical device or emergency service.

Existing reminder storage and the original reminder text are preserved. Medication timing and
dosage are never to be invented by the model. Keep .env private and do not commit API keys.
