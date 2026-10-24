---
title: Five Prompting Techniques That Actually Work in 2026
author: Priya Lindqvist (fictional)
url: https://example.com/videos/five-prompting-techniques
published: 2026-08-14
---
Hey everyone, welcome back. Today I want to walk you through five prompting techniques that I use every single day with ChatGPT and Claude, and I will show you the exact prompts so you can copy them.

The first one is a technique called role stacking. Instead of giving the model one persona, you give it two roles that disagree with each other and ask them to argue before answering. Here is the prompt I use: "You are a senior product manager and a skeptical engineer. Debate the following feature idea for three rounds, then write a joint recommendation with the risks listed first." It sounds silly, but the answers get noticeably more balanced because the model has to surface objections on its own.

The second one is what I call the checklist sandwich. The trick is to put your constraints both before and after the task, because models pay the most attention to the start and the end of the prompt. So you open with a numbered list of rules, you paste your material, and then you close with the same list again and ask the model to confirm each rule was followed.

Third, ask for a plan before the answer. My prompt for this one is simple: "Before you answer, write a short plan of the steps you will take, wait for my approval, and only then execute the plan step by step." This works incredibly well in Claude Code and in Cursor agent mode, because you catch bad assumptions before any file gets changed.

Step four is examples over adjectives. People write things like "make it punchy and professional", and the model has no idea what punchy means to you. Paste two short examples of writing you like instead and say "match the tone of these examples". In my tests this cut the number of revision rounds roughly in half.

The fifth technique is the self-review pass. After the model gives you a draft, send this prompt: "Review your previous answer as a strict editor. List the three weakest points and rewrite only those parts." It is cheap, it takes ten seconds, and it catches most of the lazy generalities.

Now, a quick business idea for anyone listening. You could build a small prompt library tool for customer support teams that stores tested prompts, tracks which ones get the best customer ratings, and suggests improvements. Support teams already pay around $30 per seat for macros software, so a prompt layer on top is an easy sell.

Pro tip before I go: keep your best prompts in a plain text file or in a notes app like Obsidian or Notion, with the date and the model version next to each one, because what works on one model version does not always carry over to the next.

That is it for today. Try one of these techniques this week and tell me which one made the biggest difference.
