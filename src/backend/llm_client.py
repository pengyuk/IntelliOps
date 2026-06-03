import os
from typing import Dict, Any, Optional

class LLMClient:
    """Minimal LLM client wrapper for future integration.

    Current prototype uses a local stub when no provider is configured.
    """

    def __init__(self, provider: Optional[str] = None):
        self.provider = (provider or os.environ.get('LLM_PROVIDER', 'none')).lower()

    def infer(self, prompt: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self.provider == 'openai':
            try:
                import openai
            except ImportError as exc:
                raise RuntimeError('openai package is not installed; install it or set LLM_PROVIDER to none') from exc
            api_key = os.environ.get('OPENAI_API_KEY')
            if not api_key:
                raise RuntimeError('OPENAI_API_KEY is not set')
            openai.api_key = api_key
            response = openai.ChatCompletion.create(
                model=os.environ.get('OPENAI_MODEL', 'gpt-4o-mini'),
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.0,
            )
            text = response.choices[0].message['content']
            return {'text': text, 'provider': 'openai'}

        if self.provider == 'anthropic':
            try:
                import anthropic
            except ImportError as exc:
                raise RuntimeError('anthropic package is not installed; install it or set LLM_PROVIDER to none') from exc
            client = anthropic.Client(api_key=os.environ.get('ANTHROPIC_API_KEY', ''))
            if not client.api_key:
                raise RuntimeError('ANTHROPIC_API_KEY is not set')
            prompt_text = f"\n\nHuman: {prompt}\n\nAssistant:"
            response = client.completions.create(
                model=os.environ.get('ANTHROPIC_MODEL', 'claude-3.0-mini'),
                prompt=prompt_text,
                max_tokens_to_generate=512,
            )
            text = response.completion
            return {'text': text, 'provider': 'anthropic'}

        return {
            'text': 'LLM provider is not configured. This is a local prototype stub.',
            'provider': 'stub',
        }
