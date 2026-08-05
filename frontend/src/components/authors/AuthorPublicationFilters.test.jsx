import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import AuthorPublicationFilters from "./AuthorPublicationFilters";
import {
  clonePublicationFilters,
  emptyPublicationFilters,
} from "./publicationFilters";

const FACETS = {
  sources: [
    { value: "openalex", label: "OpenAlex", count: 10 },
    { value: "arxiv", label: "arXiv", count: 4 },
  ],
  venues: [
    { value: "nature medicine", label: "Nature Medicine", count: 18 },
    { value: "science", label: "Science", count: 7 },
    { value: "cell", label: "Cell", count: 3 },
    { value: "lancet", label: "The Lancet", count: 2 },
  ],
  grants: [
    {
      grant_number: "R01GM123456",
      publication_count: 12,
      funder: "NIH",
    },
  ],
  authors: [],
};

function openAutocomplete(label) {
  const input = screen.getByLabelText(label);
  fireEvent.mouseDown(input);
  fireEvent.click(input);
  return input;
}

function StatefulFilters({
  initialDraft = emptyPublicationFilters(),
  initialApplied = emptyPublicationFilters(),
  onDraftChange = vi.fn(),
  onApply = vi.fn(),
  onReset = vi.fn(),
  onRemoveChip = vi.fn(),
  ...rest
}) {
  const [draftFilters, setDraftFilters] = useState(() =>
    clonePublicationFilters(initialDraft),
  );
  const [appliedFilters] = useState(() => clonePublicationFilters(initialApplied));

  return (
    <AuthorPublicationFilters
      authors={[{ id: "A1", display_name: "Ada" }]}
      draftFilters={draftFilters}
      appliedFilters={appliedFilters}
      onDraftChange={(next) => {
        onDraftChange(next);
        setDraftFilters(next);
      }}
      onApply={onApply}
      onReset={onReset}
      onRemoveChip={onRemoveChip}
      facets={FACETS}
      {...rest}
    />
  );
}

function renderFilters(overrides = {}) {
  const onDraftChange = overrides.onDraftChange ?? vi.fn();
  const onApply = overrides.onApply ?? vi.fn();
  const onReset = overrides.onReset ?? vi.fn();

  render(
    <StatefulFilters
      initialDraft={overrides.draftFilters}
      initialApplied={overrides.appliedFilters}
      onDraftChange={onDraftChange}
      onApply={onApply}
      onReset={onReset}
      onRemoveChip={overrides.onRemoveChip}
      {...overrides}
    />,
  );

  return { onDraftChange, onApply, onReset };
}

describe("AuthorPublicationFilters checkbox multi-select", () => {
  it("keeps the dropdown open while checking multiple source options", () => {
    const { onDraftChange, onApply } = renderFilters();

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    openAutocomplete("Source");

    const listbox = screen.getByRole("listbox");
    expect(within(listbox).getAllByRole("checkbox")).toHaveLength(2);

    fireEvent.click(within(listbox).getByText("OpenAlex"));
    expect(onDraftChange).toHaveBeenCalled();
    expect(onApply).not.toHaveBeenCalled();
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    fireEvent.click(within(screen.getByRole("listbox")).getByText("arXiv"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    const lastDraft = onDraftChange.mock.calls.at(-1)[0];
    expect(lastDraft.sources).toEqual(["openalex", "arxiv"]);
  });

  it("shows limited chips and a +N more chip for long venue selections", () => {
    renderFilters({
      draftFilters: {
        ...emptyPublicationFilters(),
        venues: FACETS.venues,
      },
    });

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));

    expect(screen.getByText("Nature Medicine")).toBeInTheDocument();
    expect(screen.getByText("+3")).toBeInTheDocument();
    expect(screen.queryByText("Science")).not.toBeInTheDocument();
    expect(screen.queryByText("Cell")).not.toBeInTheDocument();
  });

  it("does not call onApply when draft checkbox selection changes", () => {
    const { onDraftChange, onApply } = renderFilters();

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    openAutocomplete("Journal / Venue");
    const listbox = screen.getByRole("listbox");
    fireEvent.click(within(listbox).getByText("Nature Medicine"));

    expect(onDraftChange).toHaveBeenCalled();
    expect(onApply).not.toHaveBeenCalled();
  });

  it("calls onApply once when Apply filters is clicked", () => {
    const draft = {
      ...emptyPublicationFilters(),
      sources: ["openalex"],
    };
    const { onApply } = renderFilters({
      draftFilters: draft,
      appliedFilters: emptyPublicationFilters(),
    });

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));

    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply.mock.calls[0][0].sources).toEqual(["openalex"]);
  });

  it("clears draft selections and calls onReset", () => {
    const { onDraftChange, onReset } = renderFilters({
      draftFilters: {
        ...emptyPublicationFilters(),
        sources: ["openalex"],
        venues: [FACETS.venues[0]],
      },
    });

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));

    expect(onReset).toHaveBeenCalledTimes(1);
    expect(onDraftChange).toHaveBeenCalledWith(emptyPublicationFilters());
  });

  it("renders grant secondary text with count and funder", () => {
    renderFilters();

    fireEvent.click(screen.getByRole("button", { name: "Show filters" }));
    openAutocomplete("Grant");
    const listbox = screen.getByRole("listbox");

    expect(within(listbox).getByText("R01GM123456")).toBeInTheDocument();
    expect(within(listbox).getByText("12 publications · NIH")).toBeInTheDocument();
    expect(within(listbox).getByRole("checkbox")).toBeInTheDocument();
  });
});
