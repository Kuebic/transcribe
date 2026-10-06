# Transcribe

A single-user web app at `http://transcribe.lan` that turns Recordings (phone calls, lectures, talks) into Transcripts with Whisper `large-v3` on the home GPU box. Pick one or more audio files, choose a Kind, and come back when the Job is Done to read, play and copy the Transcript.

The terms used here and in the code (Recording, Kind, Transcript, Segment, Job) are defined in [`GLOSSARY.md`](GLOSSARY.md).

## LAN-only, no login

The app has no authentication, no sessions and no public hostname. It is reached only over plain HTTP from the home network, through the home Caddy proxy. The home network is the trust boundary, so uploading from the phone only works on home Wi-Fi. Do not publish it to the internet; see [ADR 0001](docs/adr/0001-lan-only-no-auth.md) for why, and how to get HTTPS later without exposing it.

## What the GPU box needs

- Docker with Compose v2.
- An NVIDIA GPU with about 10 GB of free VRAM for `large-v3` in fp16.
- NVIDIA driver 580 or newer (the image runs on CUDA 13.0) and the NVIDIA Container Toolkit, set up the same way as for the Ollama stack.

## Bring it up

On the GPU box:

```sh
git clone <this repo> transcribe
cd transcribe
docker compose up -d --build
```

The app listens on host port 3002. Check it with:

```sh
curl http://localhost:3002/healthz
```

The first Job downloads the `large-v3` model (about 3 GB) into the data directory; later Jobs and container restarts reuse it.

## Update

Compose builds the image from this checkout rather than pulling it from a registry, so an update is a pull of the repo and a rebuild:

```sh
git pull
docker compose up -d --build
```

Jobs interrupted by the restart go back to Queued and run again when the app starts.

## Make `http://transcribe.lan` resolve

1. **Router hostname.** On the home router's local DNS, add a host entry `transcribe.lan` pointing at the IP of the machine running Caddy (the same place the other `.lan` names point).
2. **Caddy.** Add this block to the home Caddyfile and reload Caddy:

   ```caddyfile
   http://transcribe.lan {
   	reverse_proxy super-ai-ct.lan:3002
   }
   ```

   The `http://` prefix keeps Caddy from trying to get a certificate for a `.lan` name. Caddy has no request body limit by default; the app itself rejects anything over 2 GB.

Then open `http://transcribe.lan` from the phone or the desktop.

## Backup

All state lives in one directory: `data/` next to `compose.yaml`, mounted in the container as `/data`. Add that one path to the restic backup.

```
data/
├── transcribe.sqlite3   Recordings, Kinds, Segments and Jobs
├── audio/               the audio, named by content hash
└── models/              the Whisper model cache
```

`models/` can be re-downloaded, so it may be excluded from the backup to save about 3 GB. The container runs as root, so files in `data/` are owned by root.

## GPU smoke test

The normal test suite uses a fake Transcriber and never needs a GPU. One test runs the real Whisper Transcriber end to end; it is skipped unless `TRANSCRIBE_SMOKE_AUDIO` names an audio file. Run it by hand on the GPU box, inside the image, after copying a short recording into `data/`:

```sh
cp ~/some-short-recording.m4a data/smoke.m4a
docker compose run --rm -e TRANSCRIBE_SMOKE_AUDIO=/data/smoke.m4a transcribe \
    pytest tests/test_whisper_smoke.py
```

It uses the same model cache as the app (`/data/models`), so it downloads `large-v3` only if the app has not already done so. Delete `data/smoke.m4a` afterwards.

## Phone playback

The app stores and serves each Recording's audio exactly as it was uploaded; there is no transcoding in v1. Transcription works for every accepted format (m4a, mp3, ogg, opus, wav, flac, aac, webm) because ffmpeg decodes it on the server, but playback happens in the browser, and some phone browsers cannot play some call-recording containers. If the player on a Recording page stays silent on the phone, play it on the desktop; the Transcript and copy buttons work either way.

## Development

```sh
uv sync
uv run pytest
```

Whisper is an optional extra that only the image installs; tests substitute a fake Transcriber.
