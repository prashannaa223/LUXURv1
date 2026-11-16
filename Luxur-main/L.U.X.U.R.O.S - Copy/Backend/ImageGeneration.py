import asyncio
from random import randint
from PIL import Image
import requests
from dotenv import dotenv_values
import os
from time import sleep

env_vars = dotenv_values(".env")
HuggingFaceAPIKey = env_vars.get("HuggingFaceAPIKey")


def open_images(prompt):
    folder_path = r"Data"
    prompt = prompt.replace(" ", "_")
    files = [f"{prompt}{i}.jpg" for i in range(1, 5)]
    for jpg_file in files:
        image_path = os.path.join(folder_path, jpg_file)

        try:
            img = Image.open(image_path)
            print(f"Opening image: {image_path}")
            img.show()
            sleep(1)
        except IOError:
            print(f"Error opening image: {image_path}. File may not exist or is not a valid image.")


API_URL = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
headers = {"Authorization": f"Bearer {HuggingFaceAPIKey}"}


async def query(payload):
    response = await asyncio.to_thread(requests.post, API_URL, headers=headers, json=payload)
    return response.content


async def generate_image(prompt: str):
    tasks = []
    for _ in range(4):
        payload = {
            "inputs": f"{prompt}, quality=4K, sharpness=maximum, Ultra High details, high resolution, seed = {randint(0, 1000000)}",
        }
        task = asyncio.create_task(query(payload))
        tasks.append(task)

    image_bytes_list = await asyncio.gather(*tasks)
    for i, image_bytes in enumerate(image_bytes_list):
        with open(fr"Data\{prompt.replace(' ', '_')}{i + 1}.jpg", "wb") as f:
            f.write(image_bytes)


def GenerateImage(prompt: str):
    asyncio.run(generate_image(prompt))
    open_images(prompt)


while True:
    try:
        with open(r"Frontend\Files\ImageGeneration.data", "r", encoding='utf-8') as f:
            Data: str = f.read()

        if "," not in Data:
            sleep(1)
            continue

        Prompt, Status = Data.split(",", 1)

        if Status.strip() == "True" and Prompt.strip():
            print("Generating Images ...")
            GenerateImage(prompt=Prompt.strip())

            with open(r"Frontend\Files\ImageGeneration.data", "w", encoding='utf-8') as f:
                f.write("False,False")
            break
        else:
            sleep(1)
    except Exception as e:
        print(e)
        sleep(1)
