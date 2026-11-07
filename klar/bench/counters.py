"""The tokenizers the benchmark counts with.

Two OpenAI encodings come from tiktoken; the rest are the published tokenizer.json files of open models,
fetched once from Hugging Face. Anthropic does not publish the tokenizer of its current models; the
"claude-legacy" tokenizer is the one Anthropic shipped with its SDK for earlier Claude models, so it shows
the tendency, not exact counts for today's Claude.
"""

from __future__ import annotations

from collections.abc import Callable

Counter = Callable[[str], int]

# name -> (what it is, Hugging Face repository with tokenizer.json, or None for tiktoken)
TOKENIZERS: dict[str, tuple[str, str | None]] = {
    "cl100k_base": ("GPT-4 / GPT-3.5", None),
    "o200k_base": ("GPT-4o / o-serien", None),
    "claude-legacy": ("Claude (eldre, offentlig)", "Xenova/claude-tokenizer"),
    "llama3": ("Llama 3", "NousResearch/Meta-Llama-3-8B"),
    "qwen2.5": ("Qwen 2.5", "Qwen/Qwen2.5-7B-Instruct"),
    "mistral-nemo": ("Mistral Nemo", "mistralai/Mistral-Nemo-Instruct-2407"),
    "gemma2": ("Gemma 2", "unsloth/gemma-2-9b-it"),
    "deepseek-v3": ("DeepSeek V3", "deepseek-ai/DeepSeek-V3"),
}


def load(names: list[str] | None = None) -> dict[str, Counter]:
    """Token counters by name. Downloads what is missing (needs network the first time)."""
    counters: dict[str, Counter] = {}
    for name in names or list(TOKENIZERS):
        _, repo = TOKENIZERS[name]
        if repo is None:
            import tiktoken

            enc = tiktoken.get_encoding(name)
            counters[name] = lambda s, enc=enc: len(enc.encode(s, disallowed_special=()))
        else:
            from huggingface_hub import hf_hub_download
            from tokenizers import Tokenizer

            tk = Tokenizer.from_file(hf_hub_download(repo, "tokenizer.json"))
            counters[name] = lambda s, tk=tk: len(tk.encode(s, add_special_tokens=False).ids)
    return counters


def marginal(count: Counter, word: str, before: str = "the cat") -> int:
    """Tokens a word costs in running text, with the space in front of it."""
    return count(f"{before} {word}") - count(before)
