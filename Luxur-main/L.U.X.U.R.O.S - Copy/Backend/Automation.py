import socket

_orig_getaddrinfo = socket.getaddrinfo

def _ipv4_first_getaddrinfo(*args, **kwargs):
    results = _orig_getaddrinfo(*args, **kwargs)
    ipv4 = [r for r in results if r[0] == socket.AF_INET]
    return ipv4 if ipv4 else results

socket.getaddrinfo = _ipv4_first_getaddrinfo
if socket.getdefaulttimeout() is None:
    socket.setdefaulttimeout(15)

from AppOpener import close, open as appopen
from webbrowser import open as webopen
from pywhatkit import search, playonyt
from dotenv import dotenv_values
from bs4 import BeautifulSoup
from rich import print
from groq import Groq
import webbrowser
import subprocess
import requests
import keyboard
import pyautogui
import winreg
import glob
import asyncio
import os

pyautogui.FAILSAFE = False

# Force Chrome as the browser for every webopen() call (websites, YouTube,
# Google results), regardless of the system default.
_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
CHROME_PATH = next((p for p in _CHROME_CANDIDATES if os.path.exists(p)), None)


def webopen(Url):
    if CHROME_PATH:
        subprocess.Popen([CHROME_PATH, str(Url)])
    else:
        webbrowser.open(str(Url))
    return True


if CHROME_PATH:
    # Also covers libraries that call webbrowser.open internally (pywhatkit).
    webbrowser.register("chrome", None, webbrowser.BackgroundBrowser(CHROME_PATH), preferred=True)

env_vars = dotenv_values(".env")
Username = env_vars.get("Username")
Assistantname = env_vars.get("Assistantname")
GroqAPIKey = env_vars.get("GroqAPIKey")

classes = [
    "zCubwf",
    "hgKElc",
    "LTKOO sY7ric",
    "Z0LcW",
    "gsrt vk_bk FzvWSb YwPhnf",
    "pclqee",
    "tw-Data-text tw-text-small tw-ta",
    "IZ6rdc",
    "O5Ur6d LTKOO",
    "vlzY6d",
    "webanswers-webanswers_table__webanswers-table",
    "dDoNo ikb4Bb gsrt",
    "sXLaOe",
    "LWkfKe",
    "VQF4g",
    "qv3Wpe",
    "kno-rdesc",
    "SPZz6b"
]

useragent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36'
client = Groq(api_key=GroqAPIKey)

professional_response = [
    "Your satisfaction is my priority, feel free to reach out anytime. I am here to help you with any questions or concerns you may have.",
    "I am here to provide you with the best possible assistance, so please don't hesitate to reach out to me with any questions or concerns you may have."
]

messages = []

SystemChatBot = [{"role": "system", "content": f"Hello, I am {Username}, You are a very accurate and advanced AI chatbot named {Assistantname} which has real-time up-to-date information from the internet. *** Provide Answers In a Professional Way, make sure to add full stops, commas, question marks, and use proper grammar.*** *** Just answer the question from the provided data in a professional way. ***"}]

SHORTCUT_INDEX = None

START_MENU_DIRS = [
    r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
    os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
]


def _build_shortcut_index():
    global SHORTCUT_INDEX
    if SHORTCUT_INDEX is None:
        index = []
        for base_dir in START_MENU_DIRS:
            for lnk in glob.glob(os.path.join(base_dir, "**", "*.lnk"), recursive=True):
                name = os.path.splitext(os.path.basename(lnk))[0].lower()
                index.append((name, lnk))
        SHORTCUT_INDEX = index
    return SHORTCUT_INDEX


def _find_shortcut(app):
    app_lower = app.lower().strip()
    index = _build_shortcut_index()
    for name, lnk in index:
        if name == app_lower:
            return lnk
    for name, lnk in index:
        if app_lower in name:
            return lnk
    for name, lnk in index:
        if name in app_lower:
            return lnk
    return None


def _find_in_app_paths(app):
    try:
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{app.strip()}.exe"
                with winreg.OpenKey(root, key_path) as key:
                    exe_path, _ = winreg.QueryValueEx(key, "")
                    if exe_path and os.path.exists(exe_path):
                        return exe_path
            except OSError:
                continue
    except Exception:
        pass
    return None


def GoogleSearch(Topic):
    search(Topic)
    return True


def Content(Topic):
    def OpenNotepad(file_path):
        default_text_editor = 'notepad.exe'
        subprocess.Popen([default_text_editor, file_path])

    def ContentWriterAI(prompt):
        messages.append({"role": "user", "content": f"{prompt}"})
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=SystemChatBot + messages,
            max_tokens=2048,
            temperature=0.7,
            top_p=1,
            stream=True,
            stop=None,
        )
        Answer = ""

        for chunk in completion:
            if chunk.choices[0].delta.content:
                Answer += chunk.choices[0].delta.content
        Answer = Answer.replace("</s>", "")
        messages.append({"role": "assistant", "content": f"{Answer}"})
        return Answer

    cleaned_topic = Topic.replace("content ", "")
    ContentByAI = ContentWriterAI(cleaned_topic)

    file_path = rf"Data\{cleaned_topic.lower().replace(' ', '')}.txt"
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(ContentByAI)

    OpenNotepad(file_path)
    return True


def YoutubeSearch(Topic):
    Url4Search = f"https://www.youtube.com/results?search_query={Topic}"
    webopen(Url4Search)
    return True


def PlayYoutube(query):
    playonyt(query)
    return True


def OpenApp(app, sess=requests.Session()):
    app = app.strip()

    lnk = _find_shortcut(app)
    if lnk:
        os.startfile(lnk)
        print(f"[green]Opened shortcut: {lnk}[/green]")
        return True

    exe = _find_in_app_paths(app)
    if exe:
        subprocess.Popen([exe])
        print(f"[green]Opened app: {exe}[/green]")
        return True

    try:
        appopen(app, match_closest=True, output=False, throw_errors=True)
        return True
    except Exception:
        pass

    try:
        subprocess.Popen([app, ""], shell=True)
        return True
    except Exception:
        pass

    try:
        def extract_links(html):
            if html is None:
                return []
            soup = BeautifulSoup(html, 'html.parser')
            links = soup.find_all('a', {'jsname': 'UWckNb'})
            return [link.get('href') for link in links]

        def search_google(query):
            url = f"https://www.google.com/search?q={query}"
            headers = {'User-Agent': useragent}
            response = sess.get(url, headers=headers)
            if response.status_code == 200:
                return response.text
            else:
                return None
        html = search_google(app)
        if html:
            links = extract_links(html)
            if links:
                webopen(links[0])
        return True
    except Exception:
        return False


def CloseApp(app):
    app = app.strip()
    try:
        close(app, match_closest=True, output=False, throw_errors=True)
        return True
    except Exception:
        pass
    try:
        lnk = _find_shortcut(app)
        if lnk:
            exe_name = os.path.splitext(os.path.basename(lnk))[0]
            subprocess.run(["taskkill", "/IM", f"{exe_name}.exe", "/F"],
                           capture_output=True)
            return True
    except Exception:
        pass
    try:
        subprocess.run(["taskkill", "/IM", f"{app}.exe", "/F"], capture_output=True)
        return True
    except Exception:
        return False


def System(command):
    command = command.strip().lower()

    def mute():
        keyboard.press_and_release('volume mute')

    def unmute():
        keyboard.press_and_release('volume mute')

    def volumeup():
        keyboard.press_and_release('volume up')

    def volumedown():
        keyboard.press_and_release('volume down')

    def click():
        pyautogui.click()

    def double_click():
        pyautogui.doubleClick()

    def right_click():
        pyautogui.click(button='right')

    def scroll_up():
        pyautogui.scroll(600)

    def scroll_down():
        pyautogui.scroll(-600)

    def mouse_left():
        pyautogui.moveRel(-400, 0, duration=0.25)

    def mouse_right():
        pyautogui.moveRel(400, 0, duration=0.25)

    def mouse_up():
        pyautogui.moveRel(0, -400, duration=0.25)

    def mouse_down():
        pyautogui.moveRel(0, 400, duration=0.25)

    def mouse_center():
        screen_w, screen_h = pyautogui.size()
        pyautogui.moveTo(screen_w // 2, screen_h // 2, duration=0.3)

    def show_desktop():
        keyboard.press_and_release('win+d')

    def task_view():
        keyboard.press_and_release('win+tab')

    def screenshot():
        keyboard.press_and_release('win+printscreen')

    def lock():
        keyboard.press_and_release('win+l')

    if command == "mute":
        mute()
    elif command == "unmute":
        unmute()
    elif command == "volumeup" or command == "volume up":
        volumeup()
    elif command == "volumedown" or command == "volume down":
        volumedown()
    elif command == "click":
        click()
    elif command == "double click":
        double_click()
    elif command == "right click":
        right_click()
    elif command == "scroll up":
        scroll_up()
    elif command == "scroll down":
        scroll_down()
    elif command == "mouse left" or command == "move mouse left":
        mouse_left()
    elif command == "mouse right" or command == "move mouse right":
        mouse_right()
    elif command == "mouse up" or command == "move mouse up":
        mouse_up()
    elif command == "mouse down" or command == "move mouse down":
        mouse_down()
    elif command == "mouse center" or command == "center mouse":
        mouse_center()
    elif command.startswith("move mouse to "):
        parts = command.replace("move mouse to ", "").replace(",", " ").split()
        if len(parts) >= 2:
            try:
                pyautogui.moveTo(int(parts[0]), int(parts[1]), duration=0.3)
            except ValueError:
                pass
    elif command.startswith("type "):
        pyautogui.typewrite(command[len("type "):], interval=0.03)
    elif command.startswith("press "):
        key = command[len("press "):].replace(" ", "+")
        keyboard.press_and_release(key)
    elif command == "show desktop" or command == "minimize all":
        show_desktop()
    elif command == "task view":
        task_view()
    elif command == "screenshot":
        screenshot()
    elif command == "lock":
        lock()
    else:
        print(f"[yellow]Unknown system command: {command}[/yellow]")
    return True


async def TranslateAndExecute(commands: list):
    funcs = []
    for command in commands:
        if command.startswith("open "):
            if "open it" in command:
                pass
            elif "open file" in command:
                pass
            else:
                fun = asyncio.to_thread(OpenApp, command.removeprefix("open "))
                funcs.append(fun)

        elif command.startswith("general "):
            pass
        elif command.startswith("realtime "):
            pass
        elif command.startswith("close "):
            fun = asyncio.to_thread(CloseApp, command.removeprefix("close "))
            funcs.append(fun)
        elif command.startswith("play "):
            fun = asyncio.to_thread(PlayYoutube, command.removeprefix("play "))
            funcs.append(fun)
        elif command.startswith("content "):
            fun = asyncio.to_thread(Content, command.removeprefix("content "))
            funcs.append(fun)
        elif command.startswith("google search "):
            fun = asyncio.to_thread(GoogleSearch, command.removeprefix("google search "))
            funcs.append(fun)
        elif command.startswith("youtube search "):
            fun = asyncio.to_thread(YoutubeSearch, command.removeprefix("youtube search "))
            funcs.append(fun)
        elif command.startswith("system "):
            fun = asyncio.to_thread(System, command.removeprefix("system "))
            funcs.append(fun)
        else:
            print(f"[red]Unknown command: {command}[/red]")
    results = await asyncio.gather(*funcs, return_exceptions=True)
    for result in results:
        if isinstance(result, str):
            yield result
        else:
            yield result


async def Automation(commands: list):
    async for result in TranslateAndExecute(commands):
        pass
    return True
