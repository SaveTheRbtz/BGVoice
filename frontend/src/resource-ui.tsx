import { portraitUrl } from "./api";
import { formatCount } from "./format";
import type { SourceKind } from "./gen/bgvoice/v1/pipeline_pb";
import { sourceKindLabel, toNumber } from "./pipeline-labels";
import { followLink, resourceId, voicePath } from "./routes";

export function ResourceTitle({ href, title, subtitle }: {
  href: string;
  title: string;
  subtitle: string;
}) {
  return (
    <a className="resource-title" href={href} onClick={(event) => followLink(event, href)}>
      <strong>{title}</strong>
      <span className="mono">{subtitle}</span>
    </a>
  );
}

export function VoiceLink({ voice }: { voice: string | undefined }) {
  if (voice == null) return <span className="muted">Unassigned</span>;
  const href = voicePath(voice);
  return (
    <a className="voice-link" href={href} onClick={(event) => followLink(event, href)}>
      {resourceId(voice)}
    </a>
  );
}

export function ResourceAvatar({ portrait, label }: {
  portrait: string | undefined;
  label: string;
}) {
  return (
    <span className="resource-avatar" aria-label={`${label} portrait`}>
      <span aria-hidden="true">{label.charAt(0).toUpperCase()}</span>
      {portrait != null && (
        <img
          src={portraitUrl(portrait)}
          alt=""
          onError={(event) => { event.currentTarget.hidden = true; }}
        />
      )}
    </span>
  );
}

export function DefinitionValue({ label, id, secondary = false }: {
  label: string | undefined;
  id: number | undefined;
  secondary?: boolean;
}) {
  return (
    <span className={`resolved-value ${secondary ? "is-secondary" : ""}`}>
      <strong>{label ?? "Unresolved"}</strong>
      <span className="mono">ID {formatCount(id)}</span>
    </span>
  );
}

export function SourceBadge({ kind }: { kind: SourceKind | undefined }) {
  const label = sourceKindLabel(kind);
  return <span className={`source source-${label}`}>{label}</span>;
}

export function StatusPill({ value }: { value: string }) {
  return <span className={`status-pill status-${value.replaceAll(" ", "-")}`}>{value}</span>;
}

export function Data({ label, value }: { label: string; value: string | number }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

export function ResourceData({ label, name, path }: {
  label: string;
  name: string;
  path: (name: string) => string;
}) {
  const href = path(name);
  return (
    <div>
      <dt>{label}</dt>
      <dd><a href={href} onClick={(event) => followLink(event, href)}>{resourceId(name)}</a></dd>
    </div>
  );
}

export function Metric({ label, value }: { label: string; value: number | undefined }) {
  return <div><strong>{formatCount(value)}</strong><span>{label}</span></div>;
}

export function Stat({ label, value, accent = false }: {
  label: string;
  value: bigint | undefined;
  accent?: boolean;
}) {
  return (
    <article className={`stat ${accent ? "stat-accent" : ""}`}>
      <span>{label}</span>
      <strong>{formatCount(toNumber(value))}</strong>
    </article>
  );
}

export function SupportStat({ label, value }: { label: string; value: bigint | undefined }) {
  return <div><span>{label}</span><strong>{formatCount(toNumber(value))}</strong></div>;
}
