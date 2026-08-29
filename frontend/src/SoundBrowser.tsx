import { listCharacterSounds } from "./api";
import { NumberFilter, TableBrowser, TextFilter } from "./browser";
import type { Column, FilterControls } from "./browser";
import type { CharacterSound } from "./gen/bgvoice/v1/pipeline_pb";
import { characterPath, followLink, resourceId } from "./routes";

type SoundOrder = "character" | "slot_id" | "strref";

const SOUND_COLUMNS = [
  {
    label: "Character",
    orderBy: "character",
    render: (sound) => <SoundCharacter sound={sound} />,
  },
  {
    label: "Sound slot",
    orderBy: "slot_id",
    render: (sound) => (
      <SoundSlot slotId={sound.slotId} symbols={sound.slotSymbols} groups={sound.slotGroups} />
    ),
  },
  {
    label: "Resolved sound text",
    render: (sound) => <SoundText value={sound.text} />,
  },
  {
    label: "Reference",
    orderBy: "strref",
    render: (sound) => (
      <div className="sound-reference">
        <span>Strref {sound.strref}</span>
        <span>Raw slot {sound.slotId}</span>
      </div>
    ),
  },
] satisfies readonly Column<CharacterSound, SoundOrder>[];

export function SoundBrowser() {
  return (
    <TableBrowser
      defaultOrderBy="character asc"
      loadPage={listCharacterSounds}
      columns={SOUND_COLUMNS}
      rowKey={(sound) => sound.name}
      eyebrow="CHARACTER EVIDENCE"
      title="Character sounds"
      description="Browse resolved CRE soundset text by character and semantic slot."
      noun="sounds"
      searchPlaceholder="Search characters, slots, and resolved sound text…"
      renderFilters={SoundFilters}
      tableClassName="sound-table"
    />
  );
}

function SoundFilters({ value, update }: FilterControls) {
  return (
    <>
      <TextFilter
        label="CRE resource"
        value={value("character_resource_name")}
        placeholder="IMOEN.CRE"
        onChange={(next) => update("character_resource_name", next)}
      />
      <NumberFilter
        label="Sound slot"
        value={value("slot_id")}
        onChange={(next) => update("slot_id", next)}
      />
    </>
  );
}

function SoundCharacter({ sound }: { sound: CharacterSound }) {
  const href = characterPath(sound.character);
  return (
    <a className="sound-character" href={href} onClick={(event) => followLink(event, href)}>
      <strong>{sound.characterDisplayName}</strong>
      <span className="mono">{resourceId(sound.character)}</span>
    </a>
  );
}

function SoundSlot({ slotId, symbols, groups }: {
  slotId: number;
  symbols: readonly string[];
  groups: readonly string[];
}) {
  const biography = groups.includes("BIO");
  const label = biography
    ? "Biography"
    : (symbols[0]?.replaceAll("_", " ") ?? `Slot ${slotId}`);
  return (
    <div className="sound-slot">
      <strong>{label}</strong>
      <span>{symbols.join(" · ") || `ID ${slotId}`}</span>
    </div>
  );
}

function SoundText({ value }: { value: string | undefined }) {
  if (value == null) return <span className="muted">Unresolved strref</span>;
  if (value.length <= 220) return <p className="sound-text">{value}</p>;
  return (
    <details className="sound-text expandable-copy">
      <summary aria-label="Show full sound text">{value}</summary>
      <p>{value}</p>
    </details>
  );
}
