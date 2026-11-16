# Luxur

AI voice assistant, model v1.beta.

You speak and Luxur works out what you want. It can chat, answer from live web
search, open and close apps, play music on YouTube, write content to a file,
generate images and control system volume.

## Setup (Windows)

Requires Python 3.10+ and Google Chrome (Chrome handles speech recognition).

```powershell
cd "L.U.X.U.R.O.S - Copy"
python -m venv .venv
.venv\Scripts\activate
pip install -r Backend\Requirement.txt
copy .env.example .env   # then fill in your API keys
python main.py
```

Keys you need:

| Key | Used for | Get one at |
| --- | --- | --- |
| `GroqAPIKey` | Chat, realtime answers, content writing | console.groq.com |
| `CohereAPIKey` | Deciding what kind of request you made | dashboard.cohere.com |
| `HuggingFaceAPIKey` | Image generation | huggingface.co/settings/tokens |

## Using it

- **Mic button** (or `Ctrl+M`): starts or stops listening. Switching it off while Luxur is talking stops the speech.
- **Home / Chat** (or `Ctrl+1` / `Ctrl+2`): Home shows the live status core. Chat shows the conversation transcript.
- Drag the top bar to move the window. Double-click it to maximize.

Chat history is saved to `Data/ChatLog.json`. Generated images and written content also go to `Data/`.

To try one backend module on its own, run it as a module from the project folder,
e.g. `python -m Backend.Chatbot` or `python -m Backend.TextToSpeech`.

## Project layout

```
main.py                  assistant loop + app entry point
Backend/Common.py        paths, .env settings and shared helpers
Backend/Model.py         classifies each request (Cohere)
Backend/Chatbot.py       general chat (Groq)
Backend/RealtimeSearchEngine.py  answers from Google results (Groq)
Backend/Automation.py    open/close apps, YouTube, web search, content, volume
Backend/ImageGeneration.py       Hugging Face text-to-image
Backend/SpeakToText.py   speech recognition via headless Chrome
Backend/TextToSpeech.py  edge-tts + pygame playback
Frontend/GUI.py          PyQt5 interface
```

## Linux (testing only)

Windows is the supported platform. The Linux code paths (`xdg-open`, `pactl`, `pkill`)
are only there so the app can be smoke-tested on Linux. They are not maintained.

```sh
cd "L.U.X.U.R.O.S - Copy"
python -m venv .venv && . .venv/bin/activate
pip install -r Backend/Requirement.txt
cp .env.example .env   # then fill in your API keys
python main.py
```
