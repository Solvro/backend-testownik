from tiktoken import encoding_for_model

# tokenizer
enc = encoding_for_model("gpt-4o-mini")

# parameters
MAX_TOKENS = 750
SLICE_TOKENS = 600
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
            encoded = enc.encode(block)

            for i in range(0, len(encoded), SLICE_TOKENS):
                slice_tokens = encoded[i : i + SLICE_TOKENS]
                slice_text = enc.decode(slice_tokens)

                chunks.append({"text": slice_text})

            continue

        # block over limit, start new chunk
        if current_tokens + block_tokens > MAX_TOKENS:
            chunks.append({"text": "\n\n".join(current_chunk)})

            # start new chunk with overlap
            overlap = current_chunk[-OVERLAP_BLOCKS:] if OVERLAP_BLOCKS > 0 else []

            current_chunk = overlap + [block]
            current_tokens = sum(count_tokens(b) for b in current_chunk)

        else:
            current_chunk.append(block)
            current_tokens += block_tokens

        # last chunk
    if current_chunk:
        chunks.append({"text": "\n\n".join(current_chunk)})

    return chunks
