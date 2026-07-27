import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { LocaleSwitch, useLocale } from "@/lib/i18n";
import { renderWithLocale } from "@/test/render";

function LocalizedLabel() {
  const { t } = useLocale();
  return <span>{t("question")}</span>;
}

describe("localization", () => {
  it("switches the complete locale context and document language", async () => {
    const user = userEvent.setup();
    renderWithLocale(
      <>
        <LocaleSwitch />
        <LocalizedLabel />
      </>,
    );

    await user.selectOptions(screen.getByRole("combobox", { name: "Language" }), "pt");

    expect(screen.getByText("Sua pergunta")).toBeVisible();
    await waitFor(() => expect(document.documentElement).toHaveAttribute("lang", "pt-BR"));
  });
});
