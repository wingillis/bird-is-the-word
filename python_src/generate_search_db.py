import json
import requests
from toolz import dissoc
from tqdm.auto import tqdm
from bird_fun_facts import load_bird_database


def setup_search_params():
    """Setup search parameters and headers for use with searxng."""

    base_url = "http://localhost:8081/search"
    params = {
        "q": "",
        "format": "json",
        # "pageno": 1,
        # "engines": "duckduckgo,bing,brave,google",
    }
    return base_url, params


def clean_search_results(results: list[dict]):
    remove_keys = (
        "thumbnail",
        "category",
        "engines",
        "parsed_url",
        "template",
        "positions",
    )
    return list(map(lambda d: dissoc(d, *remove_keys), results))


def load_search_database():
    try:
        with open("search_db.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_search_database(search_db):
    with open("search_db.json", "w") as f:
        json.dump(search_db, f, indent=2)


def main():
    bird_db = load_bird_database()
    search_db = load_search_database()
    bird_names = list(set(bird_db) - set(search_db))
    base_url, params = setup_search_params()

    query = 'Fun facts about bird species "{name}"'

    for i, name in enumerate(tqdm(bird_names, desc="Generating search DB")):
        # setup search query
        params["q"] = query.format(name=name)
        response = requests.get(base_url, params=params)

        if response.status_code != 200:
            print("Fail")
            continue

        json_response = response.json()["results"]
        search_db[name] = clean_search_results(json_response)

        if i % 100 == 0:
            save_search_database(search_db)

    save_search_database(search_db)


if __name__ == "__main__":
    main()
