"""Shared paths, settings and helpers used by both the backend and the GUI.

All paths are resolved from this file's location, so the app works no matter
which directory it is launched from, on Windows and (for testing) on Linux.
"""
import datetime
import json
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "Data"
FILES_DIR = ROOT_DIR / "Frontend" / "Files"
GRAPHICS_DIR = ROOT_DIR / "Frontend" / "Graphics"
ENV_PATH = ROOT_DIR / ".env"
CHATLOG_PATH = DATA_DIR / "ChatLog.json"

IS_WINDOWS = sys.platform.startswith("win")

DATA_DIR.mkdir(exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)

_env = dotenv_values(ENV_PATH)


def Env(*keys, default=None):
    """Return the first non-empty value among `keys` from .env."""
    for key in keys:
        value = _env.get(key)
        if value:
            return value.strip()
    return default


def RequireEnv(*keys):
    value = Env(*keys)
    if not value:
        raise RuntimeError(f"'{keys[0]}' is missing from {ENV_PATH}. See .env.example.")
    return value


Username = Env("Username", default="User")
Assistantname = Env("Assistantname", "AssistantName", default="Luxur")
GroqModel = Env("GroqModel", default="openai/gpt-oss-120b")
CohereModel = Env("CohereModel", default="command-a-plus-05-2026")
ImageModel = Env("ImageModel", default="stabilityai/stable-diffusion-xl-base-1.0")
InputLanguage = Env("InputLanguage", default="en")
AssistantVoice = Env("AssistantVoice", default="en-CA-LiamNeural")

# How many past messages are sent to the LLM. The full log is still saved on disk.
HISTORY_LIMIT = 20


# --------------------------------------------------------------------------
# File-based state shared between the GUI thread and the assistant thread.
# --------------------------------------------------------------------------

def TempDirectoryPath(Filename):
    return FILES_DIR / Filename


def GraphicsDirectoryPath(Filename):
    return GRAPHICS_DIR / Filename


def _read(Filename, default=""):
    try:
        return TempDirectoryPath(Filename).read_text(encoding="utf-8")
    except FileNotFoundError:
        return default


def _write(Filename, Text):
    TempDirectoryPath(Filename).write_text(Text, encoding="utf-8")


def SetMicrophoneStatus(Command):
    _write("Mic.data", Command)


def GetMicrophoneStatus():
    return _read("Mic.data", "False").strip()


def SetAssistantStatus(Status):
    _write("Status.data", Status)


def GetAssistantStatus():
    return _read("Status.data").strip()


def ShowTextToScreen(Text):
    _write("Response.data", Text)


# --------------------------------------------------------------------------
# Chat log
# --------------------------------------------------------------------------

def LoadChatLog():
    try:
        with open(CHATLOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        SaveChatLog([])
        return []


def SaveChatLog(messages):
    with open(CHATLOG_PATH, "w", encoding="utf-8") as f:
        json.dump(messages, f, indent=4, ensure_ascii=False)


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------

def AnswerModifier(Answer):
    return "\n".join(line for line in Answer.split("\n") if line.strip())


QUESTION_WORDS = ["how", "what", "who", "where", "when", "why", "which", "whose",
                  "whom", "can you", "would you", "what's", "where's", "how's"]


def QueryModifier(Query):
    new_query = Query.lower().strip()
    if not new_query:
        return new_query

    is_question = any(new_query.startswith(w + " ") or f" {w} " in new_query for w in QUESTION_WORDS)
    end = "?" if is_question else "."
    if new_query[-1] in ".?!":
        new_query = new_query[:-1]
    return (new_query + end).capitalize()


def RealtimeInformation():
    now = datetime.datetime.now()
    return (
        "Use this real-time information if needed:\n"
        f"Day: {now:%A}\nDate: {now:%d}\nMonth: {now:%B}\nYear: {now:%Y}\n"
        f"Time: {now:%H} hours, {now:%M} minutes, {now:%S} seconds.\n"
    )
