import os
import subprocess
import sys
import threading
import traceback
from time import sleep

from Backend.Automation import Automation
from Backend.Chatbot import ChatBot
from Backend.Common import (
    Assistantname, Username,
    AnswerModifier, GetAssistantStatus, GetMicrophoneStatus, LoadChatLog, QueryModifier,
    SetAssistantStatus, SetMicrophoneStatus, ShowTextToScreen, TempDirectoryPath,
)
from Backend.Model import FirstLayerDMM
from Backend.PulseHub import PulseHub
from Backend.RealtimeSearchEngine import RealtimeSearchEngine
from Backend.SpeakToText import Shutdown, SpeechRecognition
from Backend.TextToSpeech import TextToSpeech
from Backend.WakeListener import StartWakeListener
from Frontend.GUI import GraphicalUserInterface

hub = PulseHub()

DefaultMessage = f'''{Username} : Hello {Assistantname}, How are you?
{Assistantname} : Welcome {Username}. I am doing well. How may I help you?'''

Functions = ["open", "close", "play", "system", "content", "google search", "youtube search"]

INTERRUPT_FILE = "Interrupt.data"
REST_PHRASES = ("rest", "take rest", "take a rest", "go to rest", "you can rest", "rest now")


def Interrupted():
    try:
        return TempDirectoryPath(INTERRUPT_FILE).read_text(encoding="utf-8").strip() == "True"
    except (FileNotFoundError, OSError):
        return False


def ClearInterrupt():
    TempDirectoryPath(INTERRUPT_FILE).write_text("False", encoding="utf-8")


def SetStatus(StatusText):
    SetAssistantStatus(StatusText)
    hub.set_voice_state(StatusText)


def ChatLogIntegration():
    lines = []
    for entry in LoadChatLog():
        if entry.get("role") == "user":
            lines.append(f"{Username} : {entry['content']}")
        elif entry.get("role") == "assistant":
            lines.append(f"{Assistantname} : {entry['content']}")
    TempDirectoryPath("Database.data").write_text(AnswerModifier("\n".join(lines)), encoding="utf-8")


def ShowChatsOnGUI():
    history = TempDirectoryPath("Database.data").read_text(encoding="utf-8")
    ShowTextToScreen(history if history.strip() else DefaultMessage)


def InitialExecution():
    SetMicrophoneStatus("False")
    SetStatus("Available ...")
    ShowTextToScreen("")
    ClearInterrupt()
    TempDirectoryPath("Rest.data").write_text("False", encoding="utf-8")
    ChatLogIntegration()
    ShowChatsOnGUI()
    hub.event_bus.publish("session.boot", {"app": "L.U.X.U.R OS V2"}, source="main")


def ReadTypedQuery():
    TypedInputPath = TempDirectoryPath("TypedInput.data")
    try:
        TypedQuery = TypedInputPath.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        TypedQuery = ""
    if TypedQuery:
        TypedInputPath.write_text("", encoding="utf-8")
    return TypedQuery


def Speak(Answer):
    ShowTextToScreen(f"{Assistantname} : {Answer}")
    SetStatus("Answering ...")
    # Playback stops when the mic button is tapped (interrupt) or the mic
    # is switched off in the GUI; the loop then listens again immediately.
    TextToSpeech(Answer, func=lambda r=None: GetMicrophoneStatus() == "True" and not Interrupted())
    ClearInterrupt()


def MainExecution():
    TypedQuery = ReadTypedQuery()
    if TypedQuery:
        Query = QueryModifier(TypedQuery)
    else:
        Query = SpeechRecognition()
    if not Query:
        return False

    task_id = hub.create_task(title=Query[:120], intent="pending")

    # "rest": stop listening, minimize; wake word / claps bring it back.
    if Query.lower().strip().rstrip(".!?") in REST_PHRASES:
        hub.update_task(task_id, "done", {"type": "rest"})
        ShowTextToScreen(f"{Assistantname} : Resting, sir. Say 'Luxur' or clap three times to wake me.")
        SetStatus("Answering ...")
        TextToSpeech("Resting now, sir. Say Luxur or clap three times to wake me.")
        SetMicrophoneStatus("False")
        TempDirectoryPath("Rest.data").write_text("True", encoding="utf-8")
        SetStatus("Available ...")
        return True

    ShowTextToScreen(f"{Username} : {Query}")
    SetStatus("Thinking ...")

    try:
        Decision = FirstLayerDMM(Query)
    except Exception as e:
        hub.update_task(task_id, "failed", {"error": str(e), "stage": "decision"})
        traceback.print_exc()
        Speak(f"I could not process that request. {e}")
        return False

    print(f"\nDecision : {Decision}\n")
    hub.update_task(task_id, "executing", {"decision": Decision},
                    plan=Decision, intent=Decision[0] if Decision else "")

    General = [" ".join(i.split()[1:]) for i in Decision if i.startswith("general")]
    Realtime = [" ".join(i.split()[1:]) for i in Decision if i.startswith("realtime")]
    MergedQuery = " and ".join(General + Realtime)

    if any(q.startswith(func) for q in Decision for func in Functions):
        from asyncio import run
        run(Automation(list(Decision)))
        hub.event_bus.publish("automation.executed", {"commands": Decision})

    for q in Decision:
        if q.startswith("generate image"):
            prompt = q.replace("generate image ", "", 1)
            hub.event_bus.publish("image.generation.started", {"prompt": prompt})
            # ImageGeneration.py polls ImageGeneration.data in a subprocess
            # (importing it directly would block on its main loop).
            TempDirectoryPath("ImageGeneration.data").write_text(f"{prompt},True", encoding="utf-8")
            subprocess.Popen([sys.executable, os.path.join("Backend", "ImageGeneration.py")],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if Realtime:
        SetStatus("Searching ...")
        Answer = RealtimeSearchEngine(QueryModifier(MergedQuery))
        hub.update_task(task_id, "done", {"type": "realtime", "answer": Answer[:500]})
        Speak(Answer)
    elif General:
        Answer = ChatBot(QueryModifier(MergedQuery))
        hub.update_task(task_id, "done", {"type": "general", "answer": Answer[:500]})
        Speak(Answer)
    elif not any(q.startswith(func) for q in Decision for func in Functions):
        hub.update_task(task_id, "failed", {"error": "no branch matched decision", "decision": Decision})

    if "exit" in Decision:
        Speak("Okay, bye!")
        hub.update_task(task_id, "done", {"type": "exit"})
        SetMicrophoneStatus("False")
        hub.shutdown()
        Shutdown()
        os._exit(0)
    return True


def FirstThread():
    while True:
        if GetMicrophoneStatus() == "True":
            try:
                MainExecution()
            except Exception as e:
                hub.event_bus.publish("error.main_loop", {"error": str(e)}, level="error")
                traceback.print_exc()
                SetStatus("Available ...")
        else:
            status = GetAssistantStatus()
            if not status.startswith(("Available ...", "Error")):
                SetStatus("Available ...")
            sleep(0.1)


if __name__ == "__main__":
    InitialExecution()
    StartWakeListener()
    threading.Thread(target=FirstThread, daemon=True).start()
    GraphicalUserInterface()
