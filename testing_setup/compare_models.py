import time
from foundry_local_sdk import Configuration, FoundryLocalManager

MODELS = ["qwen2.5-1.5b"]
LABELS = ["idea", "task", "worry", "other"]

# (note, label you would give it) -- edit these to match YOUR judgement
SAMPLES = [
    ("I forgot to email the professor about the deadline", "task"),
    ("what if I built this tool with a tiny GUI later", "idea"),
    ("what if I mess up the presentation tomorrow", "worry"),
    ("buy a phone charger cable", "task"),
    ("maybe a recursion visualizer would make a good project", "idea"),
    ("I feel like I'm falling behind everyone in my batch", "worry"),
    ("need to revise SQL joins before Friday", "task"),
    ("the sky looked really orange today", "other"),
    ("use a binary heap for that scheduling problem", "idea"),
    ("what if my laptop dies before I submit", "worry"),
    ("call mom", "task"),
    ("song stuck in my head all day", "other"),
]

PROMPT = """Classify each note as exactly one word: idea, task, worry, or other.

Note: remember to renew my library books
Label: task

Note: could add dark mode to my app someday
Label: idea

Note: what if I fail the exam next week
Label: worry

Note: the tea at that cafe was really good
Label: other

Note: {note}
Label:"""

def pick_label(text):
    text = text.lower()
    found = [(text.find(l), l) for l in LABELS if l in text]
    return min(found)[1] if found else "unparsed"

config = Configuration(app_name="thought_dump")
FoundryLocalManager.initialize(config)
manager = FoundryLocalManager.instance

for alias in MODELS:
    print(f"\n=== {alias} ===", flush=True)
    model = manager.catalog.get_model(alias)
    print("downloading/loading (first time can be slow)...", flush=True)
    model.download()
    model.load()
    try:
        client = model.get_chat_client()
        correct, total_time = 0, 0.0
        for note, expected in SAMPLES:
            start = time.perf_counter()
            reply = client.complete_chat(
                [{"role": "user", "content": PROMPT.format(note=note)}]
            ).choices[0].message.content
            took = time.perf_counter() - start
            got = pick_label(reply)
            correct += got == expected
            total_time += took
            mark = "ok " if got == expected else "XX "
            print(f"{mark}{took:5.1f}s  expected={expected:<6} got={got:<9} raw={reply!r:<30} | {note}", flush=True)
        print(f"-> {correct}/{len(SAMPLES)} correct, {total_time/len(SAMPLES):.1f}s average")
    finally:
        model.unload()