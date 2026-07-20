/** Lab-simple sentence splitter for live narration deltas. */

const MIN_SENTENCE_LENGTH = 12;

function findSentenceBoundary(text: string, from = 0): number {
  for (let i = from; i < text.length; i++) {
    const ch = text[i];
    if (ch === "." || ch === "!" || ch === "?" || ch === "…") {
      return i;
    }
  }
  return -1;
}

/**
 * Pull finished sentences from buffer+delta.
 * Short fragments (< MIN) stay attached until the next boundary or flush.
 * `emitted` is the exact prefix removed from the stream (for checksum vs final narration).
 * `sentences` are trimmed strings sent to Polly.
 */
export function appendDelta(
  buffer: string,
  delta: string,
): { sentences: string[]; rest: string; emitted: string } {
  let rest = buffer + delta;
  const sentences: string[] = [];
  let emitted = "";

  while (rest.length > 0) {
    const firstBoundary = findSentenceBoundary(rest);
    if (firstBoundary === -1) {
      break;
    }

    let end = firstBoundary;
    let candidate = rest.slice(0, end + 1).trim();

    while (candidate.length > 0 && candidate.length < MIN_SENTENCE_LENGTH) {
      const nextBoundary = findSentenceBoundary(rest, end + 1);
      if (nextBoundary === -1) {
        return { sentences, rest, emitted };
      }
      end = nextBoundary;
      candidate = rest.slice(0, end + 1).trim();
    }

    if (candidate.length === 0) {
      break;
    }

    const rawChunk = rest.slice(0, end + 1);
    sentences.push(candidate);
    emitted += rawChunk;
    rest = rest.slice(end + 1);
  }

  return { sentences, rest, emitted };
}

export function flushRemainder(rest: string): string | null {
  const trimmed = rest.trim();
  return trimmed.length > 0 ? trimmed : null;
}
