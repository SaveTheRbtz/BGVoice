import { portraitUrl } from "./api";
import { formatCount } from "./format";
import type { SourceKind } from "./gen/bgvoice/v1/pipeline_pb";
import { sourceKindLabel } from "./pipeline-labels";
import { followLink, resourceId, voicePath } from "./routes";

export function ResourceTitle({ href, title, subtitle }: {
  href: string;
  title: string;
  subtitle: string;
}) {
  return (
    <a
      className="resource-title"
      href={href}
      aria-label={`${title}, ${subtitle}`}
      onClick={(event) => followLink(event, href)}
    >
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

export function ResourceAvatar({ portrait, label, size = "large" }: {
  portrait: string | undefined;
  label: string;
  size?: "small" | "large";
}) {
  return (
    <span className={`resource-avatar resource-avatar-${size}`} aria-label={`${label} portrait`}>
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

export function Metric({ label, value }: { label: string; value: number | undefined }) {
  return <div><strong>{formatCount(value)}</strong><span>{label}</span></div>;
}
