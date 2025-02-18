import re
import json
import enum
import ollama
import requests
from tqdm.auto import tqdm
from bs4 import BeautifulSoup, Comment
from pydantic import BaseModel, Field
from fake_useragent import UserAgent
from toolz import valfilter, curry, merge, dissoc


class KeepConfidence(BaseModel):
    keep: bool
    confidence: int = Field(ge=1, le=10)


class Labels(str, enum.Enum):
    yes = "yes"
    no = "no"


class SpeciesFactClassifier(BaseModel):
    is_species_fact: Labels


class FunFact(BaseModel):
    fact: str
    bird_name: str


def load_bird_database():
    """Load the bird img database from json file. Filter out species with empty values."""
    with open("bird_db.json", "r") as f:
        return valfilter(bool, json.load(f))


def load_link_database():
    """Load the bird link database from json file."""
    with open("bird_db_links.json", "r") as f:
        return json.load(f)


def load_search_database():
    """Load the search database from json file."""
    with open("search_db.json", "r") as f:
        return json.load(f)


def get_existing_fun_facts(model: str) -> dict[str, dict] | dict:
    """Load the existing fun facts database from a file. If doesn't exist, return empty dict."""
    fname = f"bird_fact_db_{model.replace(':', '-').replace('/', '_')}.json"
    try:
        with open(fname, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def has_fun_fact(key, bird_db):
    """Check if a bird already has a fun fact."""
    return key in bird_db


def clean_html_text(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")

    for element in soup(["script", "style", "head", "header", "footer", "nav"]):
        element.decompose()

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    main_content = soup.find("main") or soup.find("article") or soup.find("body")

    if not main_content:
        return None
    
    text = main_content.get_text()
    text = re.sub(r"\s+", " ", text)
    text = text.strip()

    # remove any remaining html tags
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"[^\x00-\x7F]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def process_webpage(url: str) -> str | None:
    """Process a webpage and extract text content."""
    try:
        ua = UserAgent()
        headers = {"User-Agent": str(ua.random)}
        print("Attempting to load", url)
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code == 200:
            text = clean_html_text(response.text)
            return text
    except Exception as e:
        print("Failed to process webpage:", e)
    return None


def save_fun_fact(bird_db, model: str):
    """Save the generated fun fact to a file."""
    fname = f"bird_fact_db_{model.replace(':', '-').replace('/', '_')}.json"
    with open(fname, "w") as f:
        json.dump(bird_db, f, indent=2)


def ranking_step(
    bird_name: str, results: list[dict], model_name: str, ctx_size: int
) -> list:
    system_prompt = (
        "You are an expert website ranker. Your job "
        "is to determine if the given website is useful for describing "
        "fun facts about a bird species. You can use the text provided to help you decide. "
        "You will also return a confidence score from 1 to 10, where 10 is very confident "
        "and 1 is not confident at all. "
        "Each website is presented in XML foramt. Respond with JSON."
    )

    result_format = "<website>\n<url>{url}</url>\n<text>\n{title}\n{content}\n</text>"

    message = (
        "Determine if the following website is useful for "
        f"describing fun facts about the following bird species: {bird_name}. "
        "A website is more useful if it contains the bird name. "
        "A website is more useful if it looks like it is unique and fun. "
        "A website is less useful if it contains lists of bird species. "
        "A website is less useful if it seems to be about a different bird species or topic.\n"
    )

    responses = []
    for result in results:
        site = result_format.format(
            url=result["url"], title=result["title"], content=result["content"]
        )
        out = ollama.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message + site},
            ],
            format=KeepConfidence.model_json_schema(),
            options={"num_ctx": ctx_size, "temperature": 0},
        )
        kc = KeepConfidence.model_validate_json(out.message.content)
        responses.append(merge(result, kc.model_dump()))

    responses = list(filter(lambda x: x["keep"], responses))

    return sorted(responses, key=lambda x: x["confidence"], reverse=True)


def fact_generation_step(
    bird_name: str,
    results: list[dict],
    model_name: str,
    ctx_size: int,
    use_urls: int = 3,
) -> list:
    """Generate a fun fact using the LLM model."""
    sys_text = (
        "You are a whacky and zany bird expert. Use the text I provide you to "
        "tell me a unique and fun fact about this bird species. The text is between "
        "xml tags like <text></text>. The text may be disorganized and can come "
        "from multiple different websites. Make sure to try to use puns if "
        "possible. Your love of birds is so strong that your bird-loving "
        "personality easily comes through in your response. Respond in JSON."
    )

    content_format = (
        f"This content for the bird species with name: {bird_name}. The following  "
        "text is from multiple websites that may or may not contain information about the bird species. "
        f"Extract information only related to the specific bird species {bird_name}. "
        "\n<text>\n{text}\n</text>\n\n"
        f"Use the text to tell me a unique and fun fact about the bird species {bird_name} with puns and jokes. If the information is present, also include "
        "where the species can be found."
    )

    website_format = "<website>\n<url>{url}</url>\n<title>\n{title}</title>\n<content>{content}\n</content></website>"

    websites = []
    used_urls = []
    for result in results:
        page = process_webpage(result["url"])
        if not page:
            print("Failed to process webpage")
            continue
        websites.append(
            website_format.format(
                url=result["url"], title=result["title"], content=page
            )
        )
        used_urls.append(result["url"])
        if len(websites) >= use_urls:
            break
    
    # reverse the order of websites to have most important last
    websites = websites[::-1]
    websites_str = "\n".join(websites)

    content = content_format.format(text=websites_str)
    print("Content tokens:", len(content) // 4)

    if len(content) // 4 > (ctx_size - len(sys_text) // 4):
        # truncate content
        content = content[-(ctx_size * 4 - len(sys_text)):]

    response = ollama.chat(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": sys_text,
            },
            {
                "role": "user",
                "content": content,
            },
        ],
        format=FunFact.model_json_schema(),
        options={"num_ctx": ctx_size, "temperature": 0.4},
    )
    fun_fact = FunFact.model_validate_json(response.message.content)

    bnl = bird_name.lower().strip()
    ffbnl = fun_fact.bird_name.lower().strip()
    if bnl != ffbnl and bnl not in ffbnl:
        raise ValueError(f"Bird name mismatch: {fun_fact.bird_name} and {bird_name}")
    return merge(
        {"urls": used_urls, "website_contents": websites}, fun_fact.model_dump()
    )


def fact_classification_step(fact: dict, model_name: str, ctx_size: int) -> bool:
    """Classify a fun fact as a species fact or not."""
    system_txt = (
        "You are an expert fact checker. "
        "Classify the supplied text surrounded in <fact></fact> XML tags "
        f"as a fun bird fact related to the species {fact['bird_name']}. "
        "The websites used to generate the fact are provided in XML format. "
        "Look through the websites to determine if there is in fact any information "
        "related to the bird species. Respond with 'yes' if the fun fact came "
        "from the websites and is related to the bird species. Respond with 'no' "
        "otherwise. Respond in JSON."
    )

    fact_format = "{websites}\n<fact>{fact}</fact>\nOnce again, respond with 'yes' if the fun fact came from the websites and is related to the bird species. Respond with 'no' otherwise."

    content = fact_format.format(
        fact=fact["fact"], websites="\n".join(fact["website_contents"])
    )

    if len(content) // 4 > (ctx_size - len(system_txt) // 4):
        # truncate content
        content = content[-(ctx_size * 4 - len(system_txt)):]

    response = ollama.chat(
        model=model_name,
        messages=[
            {"role": "system", "content": system_txt},
            {
                "role": "user",
                "content": content,
            },
        ],
        format=SpeciesFactClassifier.model_json_schema(),
        options={"num_ctx": ctx_size, "temperature": 0},
    )
    return (
        SpeciesFactClassifier.model_validate_json(
            response.message.content
        ).is_species_fact
        == Labels.yes
    )


@curry
def result_has_bird_name(bird_name: str, result: dict) -> bool:
    bird_name = bird_name.lower()
    return (
        bird_name in result["title"].lower() or bird_name in result["content"].lower()
    )


WEBSITE_BLACKLIST = [
    "ebird.org",
    "birdsoftheworld.org",
]


def blacklist_filter(result: dict) -> bool:
    return not any(w in result["url"] for w in WEBSITE_BLACKLIST)


def multi_filter(filters, results: list) -> list:
    def _and(x):
        return all(f(x) for f in filters)

    return list(filter(_and, results))


def fact_pipeline(
    bird_name: str, search_results: list[dict], model_name: str, ctx_size: int
) -> dict | None:

    # check search results, make sure pages have bird name
    # print(f"Bird name: {bird_name}; search results: {len(search_results)}")
    # filter results
    bird_filter = result_has_bird_name(bird_name)

    sorted_ranks = ranking_step(bird_name, search_results, model_name, ctx_size)
    # print("To keep:", sorted_ranks)

    filtered_results = multi_filter((bird_filter, blacklist_filter), sorted_ranks)
    # print(f"Filtered results: {len(filtered_results)}")

    if not filtered_results:
        print("No results to keep")
        return None

    # use the top 3 results to generate a fun fact
    fact = fact_generation_step(
        bird_name, filtered_results, model_name, ctx_size, use_urls=3
    )

    is_in_fact_a_fact = fact_classification_step(fact, model_name, ctx_size)
    if not is_in_fact_a_fact:
        print(f"Fun fact is not a fact for {bird_name}")
        return None

    return fact


def main():
    # Load bird databases and setup
    bird_db_links = load_link_database()
    search_db = load_search_database()
    _bird_db = load_bird_database()
    bird_names = list(set(_bird_db) & set(search_db))

    # Define LLM model name; set up parameters
    model_name = "hf.co/bartowski/allenai_Llama-3.1-Tulu-3.1-8B-GGUF:Q6_K"
    ctx_size = 15_000

    # Get existing fun facts
    bird_db = get_existing_fun_facts(model_name)

    names_without_facts = list(set(bird_names) - set(bird_db))

    print(
        f"Species with facts: {len(bird_db)}; species without facts: {len(names_without_facts)}"
    )

    # Process each bird
    for name in tqdm(names_without_facts, desc="Gathering fun facts"):
        try:
            fact = fact_pipeline(name, search_db[name], model_name, ctx_size)
            if fact:
                fact["img_url"] = _bird_db[name]
                fact["species_page"] = bird_db_links[name]
                bird_db[name] = dissoc(fact, "bird_name", "website_contents")
                save_fun_fact(bird_db, model_name)
            else:
                print(f"Failed to generate fact for {name}")
        except ValueError as e:
            print(e)
            continue


if __name__ == "__main__":
    main()
