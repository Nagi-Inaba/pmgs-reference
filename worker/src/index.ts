import { PublicError } from "./errors";
import {
  errorResponse,
  methodNotAllowed,
  optionsResponse,
  textErrorResponse,
} from "./responses";
import { isApiPath, routeRequest } from "./routes";

function withoutBody(response: Response): Response {
  return new Response(null, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const api = isApiPath(url.pathname);
    if (request.method === "OPTIONS" && api) {
      return optionsResponse();
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed(api);
    }
    try {
      const response = await routeRequest(request, env);
      return request.method === "HEAD" ? withoutBody(response) : response;
    } catch (error) {
      if (error instanceof PublicError) {
        const response = api ? errorResponse(error) : textErrorResponse(error);
        return request.method === "HEAD" ? withoutBody(response) : response;
      }
      console.error(
        JSON.stringify({
          event: "unhandled_request_error",
          path: url.pathname,
          error_type: error instanceof Error ? error.name : "UnknownError",
        }),
      );
      const internal = new PublicError(500, "INTERNAL_ERROR", "internal server error");
      const response = api ? errorResponse(internal) : textErrorResponse(internal);
      return request.method === "HEAD" ? withoutBody(response) : response;
    }
  },
} satisfies ExportedHandler<Env>;
