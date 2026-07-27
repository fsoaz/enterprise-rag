import type { Metadata } from "next";
import { Source_Sans_3 } from "next/font/google";
import { cookies, headers } from "next/headers";
import { AuthGate } from "@/components/auth-gate";
import { type Locale, LocaleProvider } from "@/lib/i18n";
import "./globals.css";

const sourceSans = Source_Sans_3({
  variable: "--font-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Enterprise RAG",
  description: "Cited answers from your documents",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const cookieLocale = (await cookies()).get("locale")?.value;
  const acceptedLanguage = (await headers()).get("accept-language") ?? "";
  const locale: Locale =
    cookieLocale === "pt" || cookieLocale === "en"
      ? cookieLocale
      : acceptedLanguage.toLowerCase().startsWith("pt")
        ? "pt"
        : "en";
  return (
    <html lang={locale === "pt" ? "pt-BR" : "en"}>
      <body className={`${sourceSans.variable} antialiased`}>
        <LocaleProvider initialLocale={locale}>
          <AuthGate>{children}</AuthGate>
        </LocaleProvider>
      </body>
    </html>
  );
}
