import { listReadableItems } from "./api";
import { BrowserScaffold, OrderSelect, SelectFilter } from "./browser";
import type { FilterControls, OrderOption } from "./browser";
import { formatBytes, formatCount } from "./format";
import {
  ReadableItemKind,
  type ReadableItem,
  type TlkString,
} from "./gen/bgvoice/v1/pipeline_pb";
import { toNumber } from "./pipeline-labels";
import { SourceBadge } from "./resource-ui";
import { useBrowser } from "./use-browser";

const ITEM_KINDS = ["book", "scroll"] as const;

const ORDERS = [
  { value: "display_title asc", label: "Title" },
  { value: "engine_resource_name asc", label: "Resource" },
  { value: "text_length desc", label: "Longest" },
  { value: "text_length asc", label: "Shortest" },
  { value: "serialized_size desc", label: "Serialized size" },
] satisfies readonly OrderOption[];

export function ReadableItemBrowser() {
  const browser = useBrowser("display_title asc", listReadableItems);
  const { result, loading } = browser;
  return (
    <BrowserScaffold
      browser={browser}
      eyebrow="SOURCE TEXTS"
      title="Readable items"
      description="Books and scrolls extracted from the effective EET installation, with their resolved dialog.tlk text."
      noun="readable items"
      searchPlaceholder="Search titles, text, and resource names…"
      renderFilters={(controls) => <ReadableItemControls controls={controls} browser={browser} />}
    >
      <div className={`readable-item-list ${loading ? "is-loading" : ""}`} aria-busy={loading}>
        {result.items.map((item) => <ReadableItemCard key={item.name} item={item} />)}
        {!loading && result.items.length === 0 && (
          <div className="empty-state">No readable items match this filter.</div>
        )}
      </div>
    </BrowserScaffold>
  );
}

function ReadableItemControls({
  controls,
  browser,
}: {
  controls: FilterControls;
  browser: ReturnType<typeof useBrowser<ReadableItem>>;
}) {
  return (
    <>
      <SelectFilter
        label="Type"
        value={controls.value("kind") as "" | (typeof ITEM_KINDS)[number]}
        values={ITEM_KINDS}
        labels={{ book: "Books", scroll: "Scrolls" }}
        onChange={(value) => controls.update("kind", value)}
      />
      <OrderSelect
        value={browser.query.orderBy}
        options={ORDERS}
        onChange={browser.setOrderBy}
      />
    </>
  );
}

function ReadableItemCard({ item }: { item: ReadableItem }) {
  const kind = readableKind(item.kind);
  const kindClass = kind.toLowerCase().replace(" ", "-");
  const alternateText = item.generalDescription?.text;
  const hasAlternateText = alternateText != null && alternateText !== item.text;
  return (
    <details className="readable-item-card">
      <summary>
        <span className={`readable-item-kind is-${kindClass}`} aria-hidden="true">
          {kind.charAt(0)}
        </span>
        <span className="readable-item-title">
          <strong>{item.displayTitle}</strong>
          <span className="mono">{item.engineResourceName}</span>
        </span>
        <span className="readable-item-summary">
          <SourceBadge kind={item.source?.kind} />
          <span>{formatCount(toNumber(item.textLength))} characters</span>
          <span>{formatBytes(toNumber(item.serializedSize))}</span>
        </span>
      </summary>
      <div className="readable-item-body">
        <article className="readable-item-text" aria-label={`${item.displayTitle} text`}>
          <header>
            <span>{kind}</span>
            <span className="mono">TLK #{item.textStrref}</span>
          </header>
          <div>{item.text}</div>
        </article>
        {hasAlternateText && (
          <section className="readable-item-alternate" aria-label="Unidentified text">
            <h3>Unidentified text</h3>
            <div>{alternateText}</div>
          </section>
        )}
        <dl className="readable-item-metadata">
          <ReadableMetadata label="General title" value={tlkValue(item.generalName)} />
          <ReadableMetadata label="Identified title" value={tlkValue(item.identifiedName)} />
          <ReadableMetadata label="General text" value={tlkReference(item.generalDescription)} />
          <ReadableMetadata label="Identified text" value={tlkReference(item.identifiedDescription)} />
          <ReadableMetadata label="Item type" value={String(item.itemType)} />
          <ReadableMetadata label="ITM version" value={item.itemVersion} />
          <ReadableMetadata label="Resource source" value={item.source?.path} />
          <ReadableMetadata
            label="Artwork"
            value={[item.icon, item.groundIcon, item.descriptionImage].filter(Boolean).join(" · ")}
          />
        </dl>
      </div>
    </details>
  );
}

function ReadableMetadata({ label, value }: { label: string; value: string | undefined }) {
  if (value == null || value === "") return null;
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function tlkValue(value: TlkString | undefined): string | undefined {
  if (value == null) return undefined;
  return value.text == null ? `Unresolved · #${value.strref}` : `${value.text} · #${value.strref}`;
}

function tlkReference(value: TlkString | undefined): string | undefined {
  return value == null ? undefined : `TLK #${value.strref}`;
}

function readableKind(kind: ReadableItemKind): "Book" | "Scroll" | "Readable item" {
  if (kind === ReadableItemKind.BOOK) return "Book";
  if (kind === ReadableItemKind.SCROLL) return "Scroll";
  return "Readable item";
}
