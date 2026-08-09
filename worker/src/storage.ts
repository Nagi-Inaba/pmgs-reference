import { unavailable } from "./errors";

const DEFAULT_MAX_BUFFERED_BYTES = 8 * 1024 * 1024;

export class ArtifactReader {
  readonly #bucket: R2Bucket;
  readonly #maxReads: number;
  #reads = 0;

  constructor(bucket: R2Bucket, maxReads: number) {
    this.#bucket = bucket;
    this.#maxReads = maxReads;
  }

  get reads(): number {
    return this.#reads;
  }

  #takeRead(): void {
    this.#reads += 1;
    if (this.#reads > this.#maxReads) {
      throw unavailable("artifact read budget exceeded");
    }
  }

  async getJson(key: string, maxBytes = DEFAULT_MAX_BUFFERED_BYTES): Promise<unknown | null> {
    this.#takeRead();
    const object = await this.#bucket.get(key);
    if (object === null) {
      return null;
    }
    if (object.size > maxBytes) {
      throw unavailable("published JSON object exceeds the validated size limit");
    }
    try {
      return await object.json<unknown>();
    } catch {
      throw unavailable("published JSON object is malformed");
    }
  }

  async getObject(key: string): Promise<R2ObjectBody | null> {
    this.#takeRead();
    return await this.#bucket.get(key);
  }
}
