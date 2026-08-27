import type { Timestamp } from "@bufbuild/protobuf/wkt";

import { formatDate } from "./format";
import {
  AttributionStatus,
  DetailStatus,
  DialogueLineKind,
  RunKind,
  RunStatus,
  SourceKind,
} from "./gen/bgvoice/v1/pipeline_pb";

export function sourceKindLabel(value: SourceKind | undefined): string {
  return value == null ? "unknown" : enumLabel(SourceKind[value], "SOURCE_KIND");
}

export function detailStatusLabel(value: DetailStatus | undefined): string {
  return value == null ? "unknown" : enumLabel(DetailStatus[value], "DETAIL_STATUS");
}

export function attributionStatusLabel(value: AttributionStatus): string {
  return enumLabel(AttributionStatus[value], "ATTRIBUTION_STATUS");
}

export function lineKindLabel(value: DialogueLineKind): string {
  return enumLabel(DialogueLineKind[value], "DIALOGUE_LINE_KIND");
}

export function runKindLabel(value: RunKind): string {
  return enumLabel(RunKind[value], "RUN_KIND");
}

export function runStatusLabel(value: RunStatus): string {
  return enumLabel(RunStatus[value], "RUN_STATUS");
}

function enumLabel(value: string, prefix: string): string {
  return value.replace(`${prefix}_`, "").replaceAll("_", " ").toLowerCase();
}

export function definitionText(label: string | undefined, id: number | undefined): string {
  return label == null || id == null ? "—" : `${label} [${id}]`;
}

export function toNumber(value: bigint | number | undefined): number | undefined {
  return value == null ? undefined : Number(value);
}

export function formatTimestamp(value: Timestamp | undefined): string {
  if (value == null) return "In progress";
  const milliseconds = Number(value.seconds) * 1000 + Math.floor(value.nanos / 1_000_000);
  return formatDate(new Date(milliseconds).toISOString());
}
