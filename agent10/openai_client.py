import os

class OpenAIChatCompletionClient:
    def __init__(self):
        self.offline = os.getenv("OPENAI_OFFLINE") == "1"

    def generate(self, prompt):
        return ""