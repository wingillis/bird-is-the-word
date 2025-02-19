import re
import time
import json
import ollama
import random
import requests
from bs4 import BeautifulSoup
from tqdm.auto import tqdm
from fake_useragent import UserAgent


def load_bird_database():
    """Load the bird img database from json file."""
    with open("bird_db_v2.json", "r") as f:
        return json.load(f)


def setup_search_params():
    """Setup search parameters and headers for use with searxng."""
    ua = UserAgent()

    base_url = "http://localhost:8081/search"
    params = {
        "q": "",
        "format": "json",
        "engines": ["google", "duckduckgo"],
    }
    return ua, base_url, params


def get_existing_fun_facts(model: str) -> dict[str, dict]:
    """Get list of birds that already have fun facts.
    Example:
    {
        "Robin": {
            "img_url": "https://birdsoftheworld.org/bow/species/amecro/cur/images/amecro_0001_480x360.jpg",
            "fun_fact": "This is a fun fact about the Robin bird species.",
        },
        "Eagle": {
            "img_url": "https://birdsoftheworld.org/bow/species/amecro/cur/images/amecro_0001_480x360.jpg",
            "fun_fact": "This is a fun fact about the Eagle bird species.",
        },
        ...
    }
    """
    fname = f"bird_fact_db_{model.replace(':', '-')}.json"
    try:
        with open(fname, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def has_fun_fact(key, bird_db):
    """Check if a bird already has a fun fact."""
    return key in bird_db


def process_webpage(url, ua):
    """Process a webpage and extract text content."""
    headers = {"User-Agent": str(ua.random)}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        return re.sub(r"\s+", " ", soup.find("body").get_text())
    return None


def generate_fun_fact(model_name, key, text, sys_role, ctx_size):
    """Generate a fun fact using the LLM model."""
    content_format = f"This content for the bird species {key}.\n<text>\n{text}\n</text>\n\nUse the text to tell me a unique and fun fact about this bird species, using puns and jokes."
    return ollama.chat(
        model=model_name,
        messages=[
            sys_role,
            {
                "role": "user",
                "content": content_format,
            },
        ],
        options={"num_ctx": ctx_size, "temperature": 0.4},
    )


def save_fun_fact(bird_db, model: str):
    """Save the generated fun fact to a file."""
    fname = f"bird_fact_db_{model.replace(':', '-')}.json"
    with open(fname, "w") as f:
        json.dump(bird_db, f, indent=2)


def main():
    # Load bird database and setup
    _bird_db = load_bird_database()
    bird_names = list(_bird_db)
    random.shuffle(bird_names)

    # Setup parameters
    # model_name = "llama3.2:3b-instruct-q8_0"
    # model_name = "mistral-small:latest"
    # model_name = "granite3.1-dense:latest"
    model_name = "tulu3:latest"
    ua, base_url, params = setup_search_params()
    ctx_size = 20_000

    # Setup system role for LLM
    sys_role = {
        "role": "system",
        "content": "You are a whacky and zany bird expert. Use the text I provide you to tell me one unique and fun fact about this bird species. The text is between xml tags like <text></text>. The text may be disorganized and can come from multiple different websites. Make sure to try to use puns if possible. Your love of birds is so strong that your bird-loving personality easily comes through in your response. Don't start your response with an affirmation, like 'Sure thing!' or 'Absolutely!'",
    }

    # Get existing fun facts
    bird_db = get_existing_fun_facts(model_name)

    # Process each bird
    for name in filter(lambda k: k not in bird_db, tqdm(bird_names, desc="Gathering fun facts")):
        try:
            # Setup search query
            query = f'Fun facts about bird species "{name}"'
            params["q"] = query
            response = requests.get(base_url, params=params)

            if response.status_code != 200:
                print("Fail")
                print(response)
                time.sleep(20)
                continue

            results = response.json()["results"]

            # Check for aviandiscovery source first - preferred
            if any("aviandiscovery" in url["url"] for url in results):
                url = next(
                    url["url"] for url in results if "aviandiscovery" in url["url"]
                )
                text = process_webpage(url, ua)
                if text:
                    response = generate_fun_fact(
                        model_name, name, text, sys_role, ctx_size
                    )
                    bird_db[name] = {
                        "img_url": _bird_db[name],
                        "fun_fact": response.message.content,
                    }
            # Check for kids pages
            elif any("kids" in url["url"] for url in results):
                url = next(url["url"] for url in results if "kids" in url["url"])
                text = process_webpage(url, ua)
                if text:
                    response = generate_fun_fact(
                        model_name, name, text, sys_role, ctx_size
                    )
                    bird_db[name] = {
                        "img_url": _bird_db[name],
                        "fun_fact": response.message.content,
                    }
            # Fall back to top 3 results
            else:
                texts = []
                for url in results[:3]:
                    try:
                        text = process_webpage(url["url"], ua)
                        if text:
                            texts.append(text)
                    except Exception:
                        pass
                    time.sleep(1)

                if texts:
                    text = "\n\n".join(texts)
                    response = generate_fun_fact(
                        model_name, name, text, sys_role, ctx_size
                    )
                    bird_db[name] = {
                        "img_url": _bird_db[name],
                        "fun_fact": response.message.content,
                    }
        except OSError as e:
            print(f"Error processing {name}: {e}")
        finally:
            save_fun_fact(bird_db, model_name)
            time.sleep(1)


if __name__ == "__main__":
    main()
