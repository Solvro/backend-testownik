from django.conf import settings
from tiktoken import encoding_for_model

# tokenizer


enc = encoding_for_model(settings.OPENAI_QUIZ_MODEL if hasattr(settings, "OPENAI_QUIZ_MODEL") else "gpt-4o-mini")

# parameters
MAX_TOKENS = 1250
SLICE_TOKENS = 1000
TOKEN_OVERLAP = 150
OVERLAP_BLOCKS = 1


def count_tokens(text: str) -> int:
    return len(enc.encode(text))


def chunk_by_tokens(blocks: list[str]) -> list[dict]:
    chunks = []

    current_chunk = []
    current_tokens = 0

    for block in blocks:
        block_tokens = count_tokens(block)

        # block too big, slice it
        if block_tokens > MAX_TOKENS:
            if current_chunk:
                chunks.append({"text": "\n\n".join(current_chunk)})
                current_chunk = []
                current_tokens = 0

            encoded = enc.encode(block)
            step = SLICE_TOKENS - TOKEN_OVERLAP

            for i in range(0, len(encoded), step):
                slice_tokens = encoded[i: i + SLICE_TOKENS]
                slice_text = enc.decode(slice_tokens)

                chunks.append({"text": slice_text})

            continue

        # block over limit, start new chunk
        if current_tokens + block_tokens > MAX_TOKENS:
            if current_chunk:
                chunks.append({"text": "\n\n".join(current_chunk)})

            # start new chunk with overlap
            overlap = current_chunk[-OVERLAP_BLOCKS:] if OVERLAP_BLOCKS > 0 else []

            candidate_chunk = overlap + [block]
            candidate_tokens = sum(count_tokens(b) for b in candidate_chunk)

            if candidate_tokens > MAX_TOKENS:
                # if overlap + block exceeds limit, start new chunk with only block
                current_chunk = [block]
                current_tokens = block_tokens
            else:
                current_chunk = candidate_chunk
                current_tokens = candidate_tokens

        else:
            current_chunk.append(block)
            current_tokens += block_tokens

        # last chunk
    if current_chunk:
        chunks.append({"text": "\n\n".join(current_chunk)})

    return chunks
