import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.WALLET_V2_API_URL;

const SAFE_REQUEST_HEADERS = new Set([
  "content-type",
  "accept",
]);

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

const DANGEROUS_HEADER_PREFIXES = [
  "authorization",
  "cookie",
  "x-forwarded-",
  "x-real-ip",
  "cf-",
  "cdn-loop",
  "forwarded",
  "via",
  "x-request-id",
  "x-amzn-",
];

function allowlistedRequestHeaders(request: NextRequest): Record<string, string> {
  const headers: Record<string, string> = {};
  request.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (!SAFE_REQUEST_HEADERS.has(lower)) return;
    if (HOP_BY_HOP_HEADERS.has(lower)) return;
    if (DANGEROUS_HEADER_PREFIXES.some((prefix) => lower.startsWith(prefix))) return;
    headers[key] = value;
  });
  return headers;
}

function resolveBackendUrl(): string {
  if (!BACKEND_URL || BACKEND_URL.trim() === "") {
    throw new Error(
      "WALLET_V2_API_URL is required but not set. Configure this server-only " +
      "environment variable in Firebase App Hosting runtime configuration."
    );
  }
  return BACKEND_URL.replace(/\/+$/, "");
}

async function getIdToken(audience: string): Promise<string | null> {
  try {
    const url = `http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=${encodeURIComponent(audience)}`;
    const res = await fetch(url, {
      headers: { "Metadata-Flavor": "Google" },
    });
    if (!res.ok) {
      console.warn("wallet-v2-proxy: identity-token fetch failed with status", res.status);
      return null;
    }
    const token = await res.text();
    console.info("wallet-v2-proxy: identity-token acquired for audience", audience);
    return token;
  } catch (err) {
    console.warn("wallet-v2-proxy: identity-token fetch error", err instanceof Error ? err.message : String(err));
    return null;
  }
}

export async function GET(
  request: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return proxyRequest(request, params.path);
}

export async function POST(
  request: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return proxyRequest(request, params.path);
}

export async function PUT(
  request: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return proxyRequest(request, params.path);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return proxyRequest(request, params.path);
}

async function proxyRequest(
  request: NextRequest,
  pathSegments: string[]
): Promise<NextResponse> {
  const baseUrl = resolveBackendUrl();
  const queryString = request.nextUrl.search;
  const path = "/" + pathSegments.join("/");
  const targetUrl = `${baseUrl}${path}${queryString}`;

  const headers = allowlistedRequestHeaders(request);
  headers["host"] = new URL(baseUrl).host;

  const idToken = await getIdToken(baseUrl);
  if (idToken) {
    headers["Authorization"] = `Bearer ${idToken}`;
  }

  const body = ["GET", "HEAD"].includes(request.method)
    ? undefined
    : await request.text();

  try {
    const backendRes = await fetch(targetUrl, {
      method: request.method,
      headers,
      body,
      redirect: "manual",
    });

    const responseBody = await backendRes.text();
    const contentType = backendRes.headers.get("content-type") || "application/octet-stream";

    return new NextResponse(responseBody, {
      status: backendRes.status,
      statusText: backendRes.statusText,
      headers: {
        "content-type": contentType,
      },
    });
  } catch (err: unknown) {
    console.error(
      "wallet-v2-proxy: backend unreachable",
      err instanceof Error ? err.message : String(err)
    );
    return NextResponse.json(
      { detail: "Backend unreachable" },
      { status: 502 }
    );
  }
}
