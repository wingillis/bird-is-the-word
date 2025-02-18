# Bird's the word 🦜

A repository of fun bird facts presented in a funny, and digestible way.

I built a program to send bird facts and a bird picture as a text message.

## Installation and setup - Python

Make sure everything below is installed before running the python scripts, as they are dependent on all pieces. 

Dependencies:
- `uv` python package
- `searxng` Docker container
- Ollama

### Python

I use `uv` to run the python code in this repository. You can install `uv` with `pip` via:

```bash
pip install uv
```

The included `python_pipeline.sh` file runs the python scripts in order, and `uv` should take care of setting up the environment and package installation.

### Docker

To search the web for bird facts, I used the `searxng` Docker container.
I [included](./docker-compose.yaml) the `compose` build script in the repo for those who want to try out this project for themselves.

Once `searxng` is running, navigate to the newly made `searxng` folder, and modify the `settings.yml` file in the following way:

```yaml
search:
    formats:
        - html
        - json  # add
server:
    port: 8080  # add
    bind_address: "0.0.0.0"  # add
```

Then restart the `searxng` container to be sure it has read the updates to the settings file.

### Ollama

Make sure that you have [Ollama installed](https://ollama.com/download) on your computer, or installed in a Docker image.

Make sure Ollama is running by typing in the terminal:

```bash
ollama --version
```

If it is not (i.e., throws an error), you must run `ollama serve` in the terminal.

Download whichever LLMs you want to use with Ollama, via `ollama pull [model-name]`.

My favorite models are:

- mistral-nemo
- tulu3
- granite3.1-dense

## Installation and setup - Go

In order to use this feature, you need to have a Twilio account, and have bought and registered a phone number.

Download the version of Go that you want to use, and run `go build go_src/bird_says_words.go` in the project folder to create the program.

It expects a `config.toml` file to be located in the project folder that contains: 1) the API key for a Twilio account, and 2) the phone numbers you want to send bird facts to.

```toml
numbers = [
    "+XXXXXXXXXX",
    "+XXXXXXXXXX"
]

[twilio]
sid="SID"
auth="AUTH"
```

## Notes

I included the base [bird_db.json](./python_src/bird_db.json) file so that people who try using this project don't overwhelm the [birdsoftheworld.org](https://birdsoftheworld.org/bow/home) servers with image URL requests.

I have not double-checked the accuracy of the species facts this project generates. I do know that sometimes it mixes up the species it is talking about.