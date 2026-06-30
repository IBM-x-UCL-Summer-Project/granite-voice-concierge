import ollama

class EmbeddingService:
    def __init__(self, model_name='granite-embedding:278m'):
        self.model_name = model_name

    def get_embedding(self, content):
        """Get the embedding for the given content using the Ollama API."""
        response = ollama.embed(self.model_name, content)
        return response.embeddings[0]
