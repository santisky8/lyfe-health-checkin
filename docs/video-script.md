# Demo video script (about 3 minutes)

Record once, with the app open on person 1. Cut every wait while an answer loads.
Spoken words are in quotes. Brackets say what is on screen.

## 1. Problem (0:00-0:20)
[Home screen, logo visible]
"When you feel off, you search online. You get generic advice that knows nothing about you, and
never tells you why it applies to you. Lyfe Health Check-In is an agent that answers from your own
data and trusted sources, remembers what you tried, and shows its work for every claim."

## 2. Your week (0:20-0:40)
[Pick Person 1, week to 2016-04-25. Scroll over "Here's your week", the sleep chart, then
"Suggested from your week"]
"This is a real, anonymized Fitbit user. The agent reads their week from Zetaris: 5.7 hours of
sleep a night, down from 7.2 the week before, and 14 hours a day sitting. Before I type
anything, it suggests what to ask, and says why: each suggestion shows the numbers behind it."

## 3. Check-in (0:40-1:30)
[Click "Why has my sleep gotten worse this week". Cut the wait. Scroll the answer slowly]
"I ask why my sleep got worse. The answer is built from three things: my own numbers, marked
'your log'; trusted public sources like MedlinePlus, MyHealthfinder and a recent PubMed review,
each numbered and linked; and my past check-ins, marked 'memory'. It also says when to see a doctor."
[Tap one source number, then a "your log" chip]
"Every claim is clickable. Nothing is unexplained."
[If it asks a follow-up question, pick two options and press Send]
"If it needs more, it asks, and I can pick more than one answer."

## 4. Memory across days (1:30-2:10)
[Type in the journal: "Went to bed earlier." Save to journal. Switch Week to 2016-05-12]
"I note what I tried. A few weeks later, sleep is up to 6.3 hours, and the agent suggests
following up on my note."
[Click the new suggestion "Did this help: went to bed earlier?" Show the answer citing the memory]
"The agent remembers my note, and the check-in I made yesterday, with the date it learned it.
That memory is Meterless H-MEM: every memory carries its source, confidence and an
append-only history, so the agent can explain why it remembers something."

## 5. Show your work (2:10-2:45)
[Open "Show your work". Expand "See the SQL". Then open a memory's history. Point at "Why it
chose what it did" at the bottom]
"Show your work lists every step: the SQL it ran on Zetaris for my log and the trusted health
pages; what it recalled from H-MEM; the model, NVIDIA Nemotron, served through Meterless
Nightshift; and why it chose what it did: which sources it dropped as off-topic, and which ones
the answer cites."
[Optional, 5 s: type "chest pain and I can't breathe" to show "Please get help now"]
"Danger signs skip the AI entirely and send you to emergency help."

## 6. Close (2:45-3:00)
[Showcase site or GitHub page]
"Lyfe Health Check-In: answers from your data, sources you can check, and a memory you can audit.
Built on Zetaris, Meterless and NVIDIA Nemotron. The code is open on GitHub."

## Before recording
- Open http://localhost:8765 (local app has yesterday's check-ins for person 1).
- Avoid the red-dots, gut and skin questions: their sources sometimes come back empty.
- Run each question once before recording so you know the answer looks good.
