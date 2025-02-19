import enum
import json
import ollama
from tqdm.auto import tqdm
from pydantic import BaseModel
from toolz import valfilter, keyfilter

class Labels(str, enum.Enum):
    yes = "yes"
    no = "no"

class Classification(BaseModel):
    """Correctly identified the text as a fun fact or not."""
    label: Labels

def load_bird_db(model):
    """Load the bird img database from json file."""
    with open(f"bird_fact_db_{model.replace(':', '-')}.json", "r") as f:
        return json.load(f)

def load_fact_classifier_db(model):
    """Load the fact classifier database from json file."""
    try:
        with open(f"fact_classification_{model.replace(':', '-')}.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


# fact_model = "granite3.1-dense:latest"
fact_model = "tulu3:latest"
# fact_model = "mistral-small:latest"
classification_model = "mistral-small:latest"

bird_db = load_bird_db(fact_model)

within_length = valfilter(lambda x: len(x["fun_fact"]) < 1500, bird_db)

print(f"Total number of fun facts: {len(bird_db)}")
print(f"Number of fun facts within length: {len(within_length)}")

fact_classification = load_fact_classifier_db(fact_model)

system_txt = (
    "Classify the text supplied by the user as a fun bird fact written with humor "
    "or not by replying \"yes\" for a fun bird fact or \"no\" for something else. Here are examples "
    "to classify as \"no\": lists of bird species, a story about someone's "
    "vacation, bullet points (- Bird: ..., - Fact: ...), gibberish."
)

# classify if fun fact, store results in a dict
for bird in filter(lambda x: x not in fact_classification, tqdm(within_length, desc="Classifying fun facts")):
    try:
        text = bird_db[bird]['fun_fact']
        response = ollama.chat(
            model=classification_model,
            messages=[
                {"role": "system", "content": system_txt},
                {"role": "user", "content": text},
            ],
            format=Classification.model_json_schema(),
            options={"num_ctx": 5_000, "temperature": 0},
        )
        val = Classification.model_validate_json(response.message.content)
        fact_classification[bird] = val.label == Labels.yes
        with open(f"fact_classification_{fact_model.replace(':', '-')}.json", "w") as f:
            json.dump(fact_classification, f, indent=2)
    except Exception as e:
        print(e)
        continue

# filter the fun facts
filtered_bird_db = keyfilter(lambda x: fact_classification.get(x, False), bird_db)

with open(f"filtered_bird_db_{fact_model.replace(':', '-')}.json", "w") as f:
    json.dump(filtered_bird_db, f, indent=2)
