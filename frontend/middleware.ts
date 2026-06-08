import { NextRequest, NextResponse } from "next/server";

function unauthorizedResponse(): NextResponse {
  return new NextResponse("Authentication required", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="Cowboy Dashboard", charset="UTF-8"',
      "Cache-Control": "no-store",
    },
  });
}

export function middleware(req: NextRequest): NextResponse {
  const basicUser = process.env.FRONTEND_BASIC_AUTH_USER ?? "";
  const basicPass = process.env.FRONTEND_BASIC_AUTH_PASS ?? "";

  if (!basicUser || !basicPass) return NextResponse.next();

  const auth = req.headers.get("authorization");
  if (!auth || !auth.startsWith("Basic ")) return unauthorizedResponse();

  const encoded = auth.slice(6).trim();
  let decoded = "";
  try {
    decoded = atob(encoded);
  } catch {
    return unauthorizedResponse();
  }

  const sep = decoded.indexOf(":");
  if (sep < 0) return unauthorizedResponse();

  const user = decoded.slice(0, sep);
  const pass = decoded.slice(sep + 1);
  if (user !== basicUser || pass !== basicPass) return unauthorizedResponse();

  return NextResponse.next();
}

export const config = {
  matcher: ["/"],
};
