const countFormatter = new Intl.NumberFormat("en-US");
const dateFormatter = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatCount(value: number | null | undefined): string {
  return value == null ? "—" : countFormatter.format(value);
}

export function formatBytes(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value < 1024) return `${value} B`;

  const kibibytes = value / 1024;
  if (kibibytes < 1024) return formatUnit(kibibytes, "KiB");

  const mebibytes = kibibytes / 1024;
  if (mebibytes < 1024) return formatUnit(mebibytes, "MiB");

  return formatUnit(mebibytes / 1024, "GiB");
}

export function formatDate(value: string | null): string {
  if (value == null) return "In progress";
  return dateFormatter.format(new Date(value));
}

export function formatHex(value: number): string {
  return `0x${value.toString(16).toUpperCase().padStart(8, "0")}`;
}

function formatUnit(value: number, unit: "KiB" | "MiB" | "GiB"): string {
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${unit}`;
}
