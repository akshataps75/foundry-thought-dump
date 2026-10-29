from foundry_local_sdk import Configuration, FoundryLocalManager

MODEL_ALIAS = "qwen2.5-0.5b"

# Start Foundry inside this Python process
config = Configuration(app_name="thought_dump")
FoundryLocalManager.initialize(config)
manager = FoundryLocalManager.instance

# Find the model in the catalog, download it if needed, load it into memory
model = manager.catalog.get_model(MODEL_ALIAS)
model.download()
model.load()

try:
    client = model.get_chat_client()
    messages = [
        {"role": "user", "content": "Label this note as idea, task, or worry: "
                                    "'I forgot to email the professor about the deadline'"}
    ]
    response = client.complete_chat(messages)
    print(response.choices[0].message.content)
finally:
    model.unload()  # always free the memory, even if something fails