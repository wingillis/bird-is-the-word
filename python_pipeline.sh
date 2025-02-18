# must be run from the root directory of the project
# check if folder name == "birds-the-words"
if [ ${PWD##*/} != "birds-the-words" ] && [ ${PWD##*/} != "bird-is-the-word" ]; then
    echo "Please run this script from the root directory of the project"
    exit 1
fi

set -e

cd python_src

# creates the initial database with bird names and image URLs
uv run get_bird_img_urls.py

uv run generate_search_db.py

# searches the web for fun bird facts, passes them through a language model
# to add personality, stores them in a new database
uv run bird_fun_facts.py

# deletes any entries that weren't processed correctly, leading to non-facts
uv run post_process_facts.py
