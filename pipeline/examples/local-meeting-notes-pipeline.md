---
title: Building a Local-First Meeting Notes Pipeline
author: Tomas Okafor (fictional)
url: https://example.com/videos/local-meeting-notes
published: 2026-08-20
---
In this video I am going to show you how I built a meeting notes pipeline that runs completely on my own laptop, with no cloud transcription service and no subscription.

Here is the setup. Recordings land in a folder, a small script picks them up, Whisper transcribes the audio, a local model running in Ollama writes the summary, and the result becomes a Markdown note in Obsidian. The whole thing is about two hundred lines of Python and the code is on github.com/example-org/local-notes-pipeline if you want to follow along.

Step one is capture. I record with any app that saves an audio file and I point the recorder at a single inbox folder. Nothing fancy.

Step two is transcription. I use the Whisper small model because on my machine it transcribes one hour of audio in roughly six minutes, which is fast enough to run overnight. The key is to normalise the audio with ffmpeg first, because Whisper gets confused by very quiet recordings.

Step three is the summary. The workflow is to send the transcript to Llama running in Ollama with a fixed prompt. The prompt I use is: "Summarise this meeting in five bullet points, then list every decision, every open question and every action item with an owner." Keeping the prompt fixed matters, because it makes every note look the same and you can search them later.

Step four is filing. The script writes the note with frontmatter, tags and a link to the project note, then moves the audio to an archive folder so it never gets processed twice. I keep a small state file with the hash of every processed recording. That one detail saved me from a lot of duplicate notes.

A pattern I really like here is what I call the overnight queue: nothing runs while I work, everything runs at night on a schedule, and in the morning I just read the digest. If you prefer no-code, you can wire the same flow with n8n, but I found plain Python easier to debug.

Some numbers. Over the last three months the pipeline processed 142 meetings, and I estimate it saves me about two hours a week of note-taking. The only real cost is electricity.

There is a real business opportunity here as well. You could package this as a privacy-first meeting notes appliance for law firms and clinics, who cannot send recordings to cloud services for compliance reasons. Firms like that routinely pay $200 a month for tools that solve a compliance headache.

If you try this, start small: get transcription working on one file before you automate anything else.
