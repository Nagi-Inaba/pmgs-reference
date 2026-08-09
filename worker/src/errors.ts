export class PublicError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "PublicError";
    this.status = status;
    this.code = code;
  }
}

export function unavailable(message = "published release artifacts are unavailable"): PublicError {
  return new PublicError(503, "RELEASE_UNAVAILABLE", message);
}
