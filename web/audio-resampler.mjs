// Stateful band-limited sample-rate conversion for browser microphone audio.

const DEFAULT_FILTER_TAPS = 32;
const MIN_BUFFER_CAPACITY = 4096;

function sinc(value) {
  if (Math.abs(value) < 1e-12) return 1;
  const angle = Math.PI * value;
  return Math.sin(angle) / angle;
}

function blackmanWindow(distance, halfWidth) {
  const normalized = distance / halfWidth;
  if (Math.abs(normalized) >= 1) return 0;
  return 0.42
    + 0.5 * Math.cos(Math.PI * normalized)
    + 0.08 * Math.cos(2 * Math.PI * normalized);
}

export class StreamingSincResampler {
  constructor(sourceRate, targetRate, { taps = DEFAULT_FILTER_TAPS } = {}) {
    if (!Number.isFinite(sourceRate) || sourceRate <= 0) {
      throw new RangeError("sourceRate must be positive");
    }
    if (!Number.isFinite(targetRate) || targetRate <= 0) {
      throw new RangeError("targetRate must be positive");
    }
    if (!Number.isInteger(taps) || taps < 8 || taps % 2 !== 0) {
      throw new RangeError("taps must be an even integer of at least 8");
    }
    this.sourceRate = sourceRate;
    this.targetRate = targetRate;
    this.ratio = sourceRate / targetRate;
    this.halfWidth = taps / 2;
    // Leave a transition band below the target Nyquist frequency so energy
    // above 8 kHz is attenuated before common 44.1/48 kHz inputs reach 16 kHz.
    this.cutoff = Math.min(1, targetRate / sourceRate) * 0.94;
    this.buffer = new Float32Array(MIN_BUFFER_CAPACITY);
    this.bufferOffset = 0;
    this.bufferLength = 0;
    this.bufferStartIndex = 0;
    this.totalInputSamples = 0;
    this.nextSourcePosition = 0;
  }

  process(samples) {
    if (!(samples instanceof Float32Array)) {
      throw new TypeError("samples must be a Float32Array");
    }
    if (this.sourceRate === this.targetRate) return new Float32Array(samples);
    this.#append(samples);
    return this.#drain(false);
  }

  flush() {
    if (this.sourceRate === this.targetRate) return new Float32Array(0);
    const output = this.#drain(true);
    this.reset();
    return output;
  }

  reset() {
    this.bufferOffset = 0;
    this.bufferLength = 0;
    this.bufferStartIndex = 0;
    this.totalInputSamples = 0;
    this.nextSourcePosition = 0;
  }

  #append(samples) {
    if (!samples.length) return;
    this.#ensureCapacity(this.bufferLength + samples.length);
    this.buffer.set(samples, this.bufferOffset + this.bufferLength);
    this.bufferLength += samples.length;
    this.totalInputSamples += samples.length;
  }

  #ensureCapacity(requiredLength) {
    if (this.bufferOffset + requiredLength <= this.buffer.length) return;
    if (requiredLength <= this.buffer.length) {
      this.buffer.copyWithin(
        0,
        this.bufferOffset,
        this.bufferOffset + this.bufferLength,
      );
      this.bufferOffset = 0;
      return;
    }
    let capacity = this.buffer.length;
    while (capacity < requiredLength) capacity *= 2;
    const grown = new Float32Array(capacity);
    grown.set(
      this.buffer.subarray(
        this.bufferOffset,
        this.bufferOffset + this.bufferLength,
      ),
    );
    this.buffer = grown;
    this.bufferOffset = 0;
  }

  #drain(flush) {
    const output = [];
    while (this.nextSourcePosition < this.totalInputSamples) {
      const centre = Math.floor(this.nextSourcePosition);
      if (!flush && centre + this.halfWidth >= this.totalInputSamples) break;
      output.push(this.#interpolate(this.nextSourcePosition));
      this.nextSourcePosition += this.ratio;
    }
    this.#discardConsumedInput();
    return Float32Array.from(output);
  }

  #interpolate(position) {
    const centre = Math.floor(position);
    const first = centre - this.halfWidth + 1;
    const last = centre + this.halfWidth;
    let weighted = 0;
    let weightTotal = 0;
    for (let sampleIndex = first; sampleIndex <= last; sampleIndex += 1) {
      const distance = sampleIndex - position;
      const weight = this.cutoff
        * sinc(this.cutoff * distance)
        * blackmanWindow(distance, this.halfWidth);
      weighted += this.#sampleAt(sampleIndex) * weight;
      weightTotal += weight;
    }
    return Math.abs(weightTotal) < 1e-12 ? 0 : weighted / weightTotal;
  }

  #sampleAt(sampleIndex) {
    if (sampleIndex < 0 || sampleIndex >= this.totalInputSamples) return 0;
    const relative = sampleIndex - this.bufferStartIndex;
    if (relative < 0 || relative >= this.bufferLength) return 0;
    return this.buffer[this.bufferOffset + relative];
  }

  #discardConsumedInput() {
    const discardBefore = Math.max(
      0,
      Math.floor(this.nextSourcePosition) - this.halfWidth,
    );
    const discardCount = Math.min(
      this.bufferLength,
      Math.max(0, discardBefore - this.bufferStartIndex),
    );
    this.bufferOffset += discardCount;
    this.bufferLength -= discardCount;
    this.bufferStartIndex += discardCount;
    if (!this.bufferLength) this.bufferOffset = 0;
  }
}
