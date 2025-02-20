import enum
import json
import ollama
from tqdm.auto import tqdm
from pydantic import BaseModel
from toolz import valfilter, keyfilter, partial, get


class Labels(str, enum.Enum):
    yes = "yes"
    no = "no"


class Classification(BaseModel):
    """Classification labels used to identify the text as a fun fact or not."""

    label: Labels


def load_bird_db(model):
    """Load the bird fact database from json file."""
    with open(f"bird_fact_db_{model.replace(':', '-')}.json", "r") as f:
        return json.load(f)


def load_fact_classifier_db(model):
    """Load the fact classifier database from json file, create if doesn't exist."""
    try:
        with open(f"fact_classification_{model.replace(':', '-')}.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


# fact_model = "mistral-small:latest"
# fact_model = "granite3.1-dense:latest"
fact_model = "tulu3:latest"

# classification_model = "mistral-small:latest"
classification_model = "mistral-nemo:12b-instruct-2407-q4_K_M"

bird_db = load_bird_db(fact_model)

# twilio character limit is 1600 characters, so this is a safe threshold
within_length = valfilter(lambda x: len(x["fun_fact"]) < 1500, bird_db)

print(f"Total number of fun facts: {len(bird_db)}")
print(f"Number of fun facts within length: {len(within_length)}")

fact_classification = load_fact_classifier_db(fact_model)

system_txt = (
    "Classify the text supplied by the user as a fun bird fact written with humor "
    'or not by replying "yes" for a fun bird fact or "no" for something else. Here are examples '
    'to classify as "no": lists of many bird species, a story about someone\'s '
    "vacation, bullet points (- Bird: ..., - Fact: ...), or a fact about a non-bird animal. "
)

unclassified_birds = list(set(within_length) - set(fact_classification))
print(f"Number of unclassified fun facts: {len(unclassified_birds)}")

# classify if fun fact, store results in a dict
for bird in tqdm(unclassified_birds, desc="Classifying fun facts"):
    try:
        text = bird_db[bird]["fun_fact"]
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
is_fact = partial(get, seq=fact_classification, default=False)
filtered_bird_db = keyfilter(is_fact, bird_db)

with open(f"filtered_bird_db_{fact_model.replace(':', '-')}.json", "w") as f:
    json.dump(filtered_bird_db, f, indent=2)
