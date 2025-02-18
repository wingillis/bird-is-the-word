import time
import json
import random
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from tqdm.auto import tqdm

def has_sci(link):
    """Check if link contains a scientific name. Specific to this website."""
    spans = link.find_all('span')
    for span in spans:
        if any('sci' in x for x in span.attrs.get('class', [])):
            return True
    return False

def get_bird_image_url(url, bird_name):
    """Get bird image URL for database."""
    response = requests.get(url, timeout=2)
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
    response = requests.get(url)

    if response.status_code != 200:
        print("Failed to fetch bird list")
        return

    # Parse bird links
    soup = BeautifulSoup(response.text, 'html.parser')
    links = soup.find_all('a')
    bird_links = [link for link in links if link.get('href') and 'species' in link.get('href')]
    
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

    # Load or create image database
    if Path('bird_db_v2.json').exists():
        with open('bird_db_v2.json', 'r') as f:
            bird_db_images = json.load(f)
    else:
        bird_db_images = {}

    # Download images
    keys = list(bird_db)
    random.shuffle(keys)

    # get image urls for any missing birds
    for key in filter(lambda k: k not in bird_db_images, tqdm(keys)):
        try:
            img_url = get_bird_image_url(bird_db[key], key)
            if img_url is None:
                continue
            bird_db_images[key] = img_url

            with open('bird_db_v2.json', 'w') as f:
                json.dump(bird_db_images, f, indent=2)

        except Exception as e:
            print(f"Error processing {key}: {e}")
        finally:
            time.sleep(1)  # Rate limiting

if __name__ == "__main__":
    main()