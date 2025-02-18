"""
Create a JSON database of bird species where the key is a bird name, and the value is an image URL.
"""
import time
import json
import random
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from tqdm.auto import tqdm
from fake_useragent import UserAgent

def has_sci(link: BeautifulSoup.Tag) -> bool:
    """Check if bow link contains a scientific name."""
    for span in link.find_all('span'):
        if any('sci' in x for x in span.attrs.get('class', [])):
            return True
    return False

def get_bird_image_url(url, bird_name):
    """Get bird image URL for database."""
    response = requests.get(url, timeout=3, headers={"User-Agent": UserAgent().random})
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        imgs = soup.find_all('img')

        for img in filter(lambda x: bird_name in x.get('alt', ''), imgs):
            src = img.get('src')
            if src and '320' in src:
                return src.replace('320', '480')
    return None

def main():
    # Scrape bird links
    url = "https://birdsoftheworld.org/bow/specieslist"
    response = requests.get(url, timeout=5, headers={"User-Agent": UserAgent().random})

    if response.status_code != 200:
        print("Failed to fetch bird list")
        return

    # Parse bird links
    soup = BeautifulSoup(response.text, 'html.parser')
    bird_links = [
        link
        for link in soup.find_all("a")
        if link.get("href") and "species" in link.get("href")
    ]

    print(f"Found {len(bird_links)} total links")

    # Filter for species
    species_links = list(filter(lambda x: has_sci(x), bird_links))
    print(f"Found {len(species_links)} species links")

    # Construct bird database
    base_url = "https://birdsoftheworld.org"
    bird_db = {}
    for bird in species_links:
        href = bird.get('href')
        name = bird.text.split('\n')[1]
        bird_db[name] = base_url + href

    # Load or create image url database
    if Path('bird_db.json').exists():
        with open('bird_db.json', 'r') as f:
            bird_db_images = json.load(f)
    else:
        bird_db_images = {}

    keys = list(bird_db)
    new_keys = list(set(keys) - set(bird_db_images))
    print(f"Don't have image URLS for {len(new_keys)} species")

    # spice things up
    random.shuffle(new_keys)

    # get image urls for any missing birds
    for key in tqdm(new_keys, desc="Gathering image links"):
        try:
            img_url = get_bird_image_url(bird_db[key], key)
            bird_db_images[key] = img_url

            with open('bird_db.json', 'w') as f:
                json.dump(bird_db_images, f, indent=2)

        except Exception as e:
            print(f"Error processing {key}: {e}")
        finally:
            time.sleep(0.5)  # Rate limiting

    bird_db_links = {key: bird_db[key] for key in bird_db_images}
    with open('bird_db_links.json', 'w') as f:
        json.dump(bird_db_links, f, indent=2)

if __name__ == "__main__":
    main()
