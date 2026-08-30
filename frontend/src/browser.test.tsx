// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ListQuery, ListResult } from "./api";
import { SelectFilter, TableBrowser } from "./browser";
import type { Column } from "./browser";

interface Row {
  id: string;
  name: string;
}

type Order = "name";
type LoadPage = (query: ListQuery, signal: AbortSignal) => Promise<ListResult<Row>>;

const COLUMNS = [{
  label: "Name",
  orderBy: "name",
  render: (row) => row.name,
}] satisfies readonly Column<Row, Order>[];

function renderBrowser(loadPage: LoadPage) {
  return render(
    <TableBrowser
      defaultOrderBy="name desc"
      loadPage={loadPage}
      columns={COLUMNS}
      rowKey={(row) => row.id}
      eyebrow="SOURCE"
      title="Characters"
      description="Character resources"
      noun="characters"
      searchPlaceholder="Search characters…"
      renderFilters={({ value, update }) => (
        <SelectFilter
          label="Source"
          value={value("source_kind") as "" | "override" | "bif"}
          values={["override", "bif"]}
          onChange={(value) => update("source_kind", value)}
        />
      )}
    />,
  );
}

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
  vi.restoreAllMocks();
});

describe("resource browser workflow", () => {
  it("searches by relevance, filters, sorts, and traverses cursor pages", async () => {
    window.history.replaceState(null, "", "/characters");
    const loadPage = vi.fn<LoadPage>((query): Promise<ListResult<Row>> => Promise.resolve({
      items: [{ id: query.pageToken === "next" ? "2" : "1", name: query.pageToken === "next" ? "Minsc" : "Imoen" }],
      nextPageToken: query.pageToken === "next" ? "" : "next",
      totalSize: 2n,
    }));
    const user = userEvent.setup();
    const query = () => loadPage.mock.lastCall?.[0];

    renderBrowser(loadPage);

    await screen.findByText("Imoen");
    expect(query()).toMatchObject({ orderBy: "name desc", pageSize: 25, pageToken: "" });

    await user.type(screen.getByRole("searchbox", { name: "Full-text search characters" }), "Imoen");
    await waitFor(() => expect(query()).toMatchObject({ filter: 'search("Imoen")', orderBy: "" }));
    expect(screen.getByRole("button", { name: "Relevance" }).getAttribute("aria-pressed"))
      .toBe("true");
    expect(new URLSearchParams(window.location.search).get("filter")).toBe('search("Imoen")');

    await user.click(screen.getByRole("button", { name: /Name/ }));
    await waitFor(() => expect(query()).toMatchObject({ orderBy: "name desc" }));
    await user.click(screen.getByRole("button", { name: /Name/ }));
    await waitFor(() => expect(query()).toMatchObject({ orderBy: "name asc" }));
    await user.click(screen.getByRole("button", { name: "Relevance" }));
    await waitFor(() => expect(query()).toMatchObject({ orderBy: "" }));

    await user.selectOptions(screen.getByRole("combobox", { name: "Source" }), "override");
    await waitFor(() => expect(query()).toMatchObject({
        filter: 'search("Imoen") AND source_kind = "override"',
        pageToken: "",
    }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Rows" }), "50");
    await waitFor(() => expect(query()).toMatchObject({ pageSize: 50, pageToken: "" }));

    await user.click(screen.getByRole("button", { name: "Next →" }));
    await screen.findByText("Minsc");
    expect(query()).toMatchObject({ pageToken: "next" });
    await user.click(screen.getByRole("button", { name: "← Previous" }));
    await screen.findByText("Imoen");
    expect(query()).toMatchObject({ pageToken: "" });

    await user.click(screen.getByRole("button", { name: "Clear 2" }));
    await waitFor(() => expect(query())
      .toMatchObject({ filter: "", orderBy: "name desc", pageSize: 50 }));

    const parameters = new URLSearchParams({
      filter: 'search("Minsc") AND source_kind = "bif"',
      order_by: "name asc",
      page_size: "50",
      page_token: "history-token",
    });
    window.history.pushState(null, "", `/characters?${parameters}`);
    fireEvent.popState(window);

    await waitFor(() => expect(query()).toMatchObject({
      filter: 'search("Minsc") AND source_kind = "bif"',
      orderBy: "name asc",
      pageSize: 50,
      pageToken: "history-token",
    }));
    expect(screen.getByRole("searchbox")).toBe(screen.getByDisplayValue("Minsc"));
    expect(screen.getByRole("combobox", { name: "Source" }))
      .toBe(screen.getByDisplayValue("bif"));
    expect(screen.getByRole("combobox", { name: "Rows" }))
      .toBe(screen.getByDisplayValue("50"));
  });

  it("reports a failed load without discarding the browser shell", async () => {
    const loadPage = vi.fn<(
      query: ListQuery,
      signal: AbortSignal,
    ) => Promise<ListResult<Row>>>(() => Promise.reject(new Error("database unavailable")));

    renderBrowser(loadPage);

    expect((await screen.findByRole("alert")).textContent).toContain("database unavailable");
    screen.getByRole("heading", { name: "Characters" });
  });
});
