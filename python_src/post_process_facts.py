import json
from toolz import valfilter


def load_bird_db(model):
    """Load the bird fact database from json file."""
    with open(
        f"bird_fact_db_{model.replace(':', '-').replace('/', '_')}.json", "r"
    ) as f:
        return json.load(f)


def load_fact_classifier_db(model):
    """Load the fact classifier database from json file, create if doesn't exist."""
    try:
        with open(
            f"fact_classification_{model.replace(':', '-').replace('/', '_')}.json", "r"
        ) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


fact_model = "hf.co/bartowski/allenai_Llama-3.1-Tulu-3.1-8B-GGUF:Q6_K"

bird_db = load_bird_db(fact_model)

# twilio character limit is 1600 characters, so this is a safe threshold
within_length = valfilter(lambda x: len(x["fact"]) < 1400, bird_db)

print(f"Total number of fun facts: {len(bird_db)}")
print(f"Number of fun facts within length: {len(within_length)}")


with open(
    f"filtered_bird_db_{fact_model.replace(':', '-').replace('/', '_')}.json", "w"
) as f:
    json.dump(within_length, f, indent=2)
