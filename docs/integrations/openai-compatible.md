# OpenAI-compatible provider

## What it unlocks

Connect a service that offers an OpenAI-compatible chat-completions API. This includes local model servers such as Ollama and hosted compatible services.

## Cost

Cost depends on the service and model. A local Ollama model may not have a per-request provider charge, but your computer still uses memory and processing power. Check your provider's terms.

## Get your key

1. Choose a compatible service and follow its instructions to start the API.
2. Copy its API base URL and model name. For Ollama running on the same host as Docker, the example URL is `http://host.docker.internal:11434/v1`.
3. If the service requires an API key, create one in that service's account settings.

## Connect it

In Settings, choose **OpenAI-compatible**, enter the base URL and model name, and enter a key if required. For Ollama, use a model name installed in Ollama. Select **Test**, then save.
