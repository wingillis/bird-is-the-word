# Bird's the word 🦜

A repository of fun bird facts presented in a funny, and digestible way.

I built a program to send bird facts, a bird picture, and a short bird video as a text message.

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

It expects a `config.toml` file to be located in the project folder that contains: 1) the API key for a Twilio account, 2) the Twilio phone number to send from, and 3) the phone numbers you want to send bird facts to.

```toml
numbers = [
    "+XXXXXXXXXX",
    "+XXXXXXXXXX"
]

[twilio]
sid="SID"
auth="AUTH"
number="+XXXXXXXXXX"
```

The Go script also expects a fact database and hosted video URLs:

- `bird_db.json`: the bird facts, image URLs, and species page URLs.
- `BIRD_VIDEO_BASE_URL`: the simplest way to use temporary hosting, where videos are served from local files at `{base}/{Normalized_Bird_Name}.mp4`.
- `BIRD_VIDEO_DIR`: the local directory to check for matching `.mp4` files, defaulting to `bird_videos`.
- `bird_video_urls.json`: an optional fallback manifest for permanent hosting.

For temporary local hosting, start a local file server for `bird_videos`:

```bash
python3 -m http.server 8765 --directory bird_videos
```

Then expose it with a temporary HTTPS tunnel such as ngrok:

```bash
ngrok http 8765
```

Use the HTTPS forwarding URL as `BIRD_VIDEO_BASE_URL` while the tunnel and Python server are still running:

```bash
BIRD_DB_PATH=python_src/bird_fact_db_pi.json \
BIRD_VIDEO_BASE_URL=https://abc123.ngrok-free.app \
./bird_says_words
```

The script will automatically build video URLs such as:

```text
https://abc123.ngrok-free.app/Lowland_Akalat.mp4
```

When `BIRD_VIDEO_BASE_URL` is set, the script checks local files in `BIRD_VIDEO_DIR` instead of pinging the tunnel URL. It only includes birds with a local `.mp4` file at the expected normalized filename and skips files larger than `BIRD_MAX_VIDEO_BYTES`.

If you use permanent hosting instead, leave `BIRD_VIDEO_BASE_URL` unset and create `bird_video_urls.json`. The video manifest should map either the bird name or the video's normalized bird key to the hosted video URL:

```json
{
  "Lowland Akalat": "https://example.com/bird-videos/Lowland_Akalat.mp4",
  "Cabanis_s_Ground-Sparrow": "https://example.com/bird-videos/Cabanis_s_Ground-Sparrow.mp4"
}
```

Bird video keys follow the local `bird_videos` filename convention: spaces become `_`, possessive `'s` becomes `_s`, and remaining apostrophes are removed.

For the manifest fallback, the script filters the bird list to facts with valid hosted video URLs. Each URL must:

- use public HTTPS
- serve `Content-Type: video/mp4`
- serve a `Content-Length`
- be no larger than `BIRD_MAX_VIDEO_BYTES`, which defaults to `4500000`

Twilio sends MMS media by fetching each `MediaUrl`, so the tunnel must stay running until the message is accepted and Twilio has fetched the video. Twilio Assets can host public files for a more permanent setup, and S3/R2/GCS-style public buckets also work. Public Twilio Assets are accessible to anyone with the URL, and Twilio stores uploaded files with their metadata intact, so strip metadata before upload if that matters.

You can tune the video validation with:

```bash
BIRD_MAX_VIDEO_BYTES=4500000
BIRD_VIDEO_HEAD_TIMEOUT_SECONDS=5
```

To recompress every local video for safer MMS delivery, run:

```bash
./compress_bird_videos.sh
```

The script backs up the current `bird_videos` files, re-encodes every `.mp4` as H.264/AAC MP4, validates that each output is smaller than the original and under 3.5 MB, then replaces the local files. You can align the Go sender with the same ceiling using:

```bash
BIRD_MAX_VIDEO_BYTES=3500000
```

## Notes

I included the base [bird_db.json](./python_src/bird_db.json) file so that people who try using this project don't overwhelm the [birdsoftheworld.org](https://birdsoftheworld.org/bow/home) servers with image URL requests.

I have not double-checked the accuracy of the species facts this project generates. I do know that sometimes it mixes up the species it is talking about.
