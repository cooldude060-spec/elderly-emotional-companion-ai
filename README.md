# Elderly Emotional Companion AI 💚

An AI-powered companion designed to help elderly people remember daily tasks, manage reminders, and interact through a friendly voice assistant.

Built with **Python, FastAPI, SQLite, and Nebius AI**.

## ✨ Features

- **Senior-friendly dashboard:** Clean interface with large text, accessible buttons, and a warm teal-and-cream design.
- **Reminder management:** Add reminders for medicines, appointments, hydration, and daily activities.
- **AI companion:** Generate conversational responses using a Nebius-hosted Nemotron model.
- **Voice interaction:** Capture speech through supported browser speech recognition.
- **Text-to-speech:** Speak reminder confirmations in supported browsers.
- **SQLite database:** Store reminder information locally.
- **Background scheduler:** Check due reminders periodically.
- **Optional SMS integration:** SMS is disabled unless configured.
- **Responsive design:** Dashboard adapts to desktop and smaller screens.

## 🧰 Technology Stack

| Component | Technology |
|---|---|
| Backend | Python, FastAPI |
| Frontend | HTML, CSS, JavaScript |
| Database | SQLite |
| AI | Nebius Token Factory |
| AI model | NVIDIA Nemotron 3 Nano |
| Voice input | Browser Speech Recognition API |
| Voice output | Browser Text-to-Speech API |
| API documentation | FastAPI / Swagger UI |

## 📁 Project Structure

Expected structure:

```text
elderly_companion/
├── main.py
├── .env
├── .env.example
├── requirements.txt
├── README.md
├── static/
│   └── index.html
└── memory.db
```

**Note:** `memory.db` may be created automatically by the application. Your actual project may contain additional files.

## 🚀 Setup on Windows

### 1. Open the project

Open the project folder in Visual Studio Code.

Open Terminal → New Terminal.

### 2. Create a virtual environment

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use Command Prompt:

```cmd
.venv\Scripts\activate.bat
```

### 3. Install dependencies

If `requirements.txt` exists:

```bash
pip install -r requirements.txt
```

Otherwise, install the dependencies required by your existing application. For example:

```bash
pip install fastapi uvicorn requests python-dotenv
```

Install any additional packages used by your voice input, voice output, or scheduler implementation.

### 4. Configure Nebius AI

Create a `.env` file in the project root.

Example:

```env
NEBIUS_API_KEY=your_nebius_api_key
```

Use the environment variable name expected by your `main.py`. Do not commit your actual API key to GitHub or share it publicly.

### 5. Start the backend

Run:

```bash
uvicorn main:app --reload
```

If your Python file has a different name, replace `main` with that filename.

## 🌐 Open the Application

Once the server starts, open these local URLs:

- **Dashboard:** http://127.0.0.1:8000/dashboard
- **API documentation:** http://127.0.0.1:8000/docs
- **API health check:** http://127.0.0.1:8000/

The dashboard is served by FastAPI from `static/index.html`.

To serve the dashboard, your `main.py` must configure the static directory and the `/dashboard` route.

Example:

```python
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")
```

Add this to your existing application; do not create a second FastAPI application instance.

## 🔔 Reminder Workflow

1. Open the dashboard.
2. Select **Add Reminder**.
3. Enter the reminder text and, optionally, its date and time.
4. Save the reminder.
5. Refresh the reminder list to see the stored information.
6. At the scheduled time, the backend scheduler can process due reminders according to its existing implementation.

Example reminder:

```text
Reminder: Take medicine
Due time: 10:00 AM
```

Never rely on the AI to invent medication dosages or change instructions provided by a healthcare professional.

## 🎙️ Voice Assistant

The dashboard includes a microphone button.

On supported browsers:

1. Allow microphone access when prompted.
2. Tap **Tap to Speak**.
3. Speak clearly.
4. Review the recognized text.
5. Confirm and save the reminder.

Browser speech recognition support varies. HTTPS or localhost is generally required for browser microphone access.

### Voice output

The browser can speak confirmation messages using its Text-to-Speech API.

The backend may also have its own voice output implementation. These are separate mechanisms: browser speech does not automatically prove that backend audio playback is working.

For immediate spoken AI responses, ensure the application:
- Obtains the actual AI reply.
- Uses that reply in the speech function.
- Handles speech errors.
- Avoids making up medication instructions or times.

## 🤖 AI Configuration

The project uses Nebius Token Factory to access a Nemotron model.

The configured model in the current project is:

```text
nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
```

Use the model identifier and API endpoint configured in your existing application. Model availability and API configuration can change.

The AI should:
- Use simple, reassuring language.
- Preserve the user's intended reminder.
- Avoid inventing times, dosages, or medical instructions.
- Ask for clarification when essential information is missing.

## 🔌 Backend API Endpoints

The current project has been described as exposing these endpoints. Confirm the exact request and response schemas in `/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /` | Check application status |
| `POST /add_reminder/` | Create a reminder |
| `GET /recall_reminders/` | Retrieve reminders |
| `GET /search_reminders/` | Search reminders |
| `PUT /update_reminder/{id}` | Update a reminder |
| `DELETE /delete_reminder/{id}` | Delete a reminder |
| `POST /ai_reply/` | Generate an AI response |
| `POST /voice_add_reminder/` | Process a voice-based reminder |

These methods are based on the previously described API routes. Verify each method and payload in the running Swagger documentation.

## 🗄️ Database

SQLite provides local storage for reminder records.

The application may create its database automatically. Back up the database before making schema changes or deleting records.

Do not store API keys, passwords, or unnecessary sensitive medical information in plain text.

## 🛠️ Troubleshooting

### Dashboard returns 404

- Confirm that `static/index.html` exists.
- Check that the `/dashboard` route is registered.
- Restart Uvicorn after changing backend code.

### Reminders do not appear

- Open `/docs` and test `GET /recall_reminders/`.
- Check the backend terminal for errors.
- Verify that the frontend reads the actual response format returned by the endpoint.

### Reminder cannot be saved

- Inspect the request in the browser's Developer Tools.
- Check the payload and field names expected by `POST /add_reminder/`.
- Confirm the database is writable.

### Voice input does not work

- Try Chrome on localhost.
- Allow microphone permission.
- Check whether browser speech recognition is supported.
- Use the text-based reminder form as a fallback.

### AI response is missing

- Check that the Nebius API key is configured.
- Verify the model identifier and API endpoint.
- Inspect the backend terminal for API errors.
- Confirm that the response field returned by the AI function is used by the frontend.

### No voice after saving a reminder

- Test browser Text-to-Speech separately.
- Check whether the AI reply is actually returned.
- Confirm that the speech function receives the intended text.
- Test backend voice playback separately if the project uses a server-side speech engine.

## 🔒 Security Notes

- Never commit `.env` or API credentials.
- Add authentication before exposing the application beyond localhost.
- Validate reminder text and date/time values on the server.
- Protect personal and medical information.
- Use secure authentication and authorization for any future family-access feature.

## 🗺️ Future Enhancements

- Fully connected voice-to-reminder workflow.
- Spoken AI replies immediately after saving.
- Family dashboard with appropriate access controls.
- Reminder editing and deletion from the UI.
- Hindi and English language selection.
- Reliable notifications for due reminders.
- Improved error handling and automated tests.

## ❤️ Project Goal

Help elderly people feel supported, remember important daily tasks, and interact with technology through a simple, reassuring AI companion.

**Built to make everyday life easier — one reminder at a time.**
