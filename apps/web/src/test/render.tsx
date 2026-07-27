import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { type Locale, LocaleProvider } from "@/lib/i18n";

export function renderWithLocale(ui: ReactElement, locale: Locale = "en") {
  return render(<LocaleProvider initialLocale={locale}>{ui}</LocaleProvider>);
}
