# Transcribe

A single-user, LAN-only web app for uploading audio recordings and turning them into text that can be pasted into LLM prompts. Transcription runs on the owner's own GPU box. Cleaning up the text is done outside the app, by the owner, with whatever LLM they like.

## Language

**Recording**:
One uploaded audio file and everything derived from it. There is one kind of Recording; calls and lectures differ only by Kind.
_Avoid_: Upload, file, audio, session

**Kind**:
The label that sorts Recordings into groups (e.g. call, lecture). A Recording has exactly one Kind. Kinds are the only grouping in the app.
_Avoid_: Folder, type, category, tag

**Transcript**:
The text Whisper produced for a Recording, untouched by any later cleanup. Made of Segments.
_Avoid_: Raw transcript, output, caption

**Segment**:
One timestamped run of speech within a Transcript, as Whisper emitted it. The unit for "copy with timestamps" and for jumping playback to a spot.
_Avoid_: Line, chunk, cue

**Job**:
The server-side transcription of one Recording. Starts after upload, outlives the browser tab, and can be retried if it fails.
_Avoid_: Task, process, run
