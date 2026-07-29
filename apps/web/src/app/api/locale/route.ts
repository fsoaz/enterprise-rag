import { type NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest): Promise<NextResponse> {
  let body: { locale?: unknown };
  try {
    body = (await request.json()) as { locale?: unknown };
  } catch {
    return NextResponse.json({ detail: "Unsupported locale" }, { status: 422 });
  }
  if (body.locale !== "en" && body.locale !== "pt") {
    return NextResponse.json({ detail: "Unsupported locale" }, { status: 422 });
  }
  const response = NextResponse.json({ locale: body.locale });
  response.cookies.set("locale", body.locale, {
    httpOnly: true,
    sameSite: "lax",
    secure: request.nextUrl.protocol === "https:",
    path: "/",
    maxAge: 31_536_000,
  });
  return response;
}
