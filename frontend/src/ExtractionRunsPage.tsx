import { listExtractionRuns } from "./api";
import { TableBrowser } from "./browser";
import type { Column } from "./browser";
import { formatCount } from "./format";
import type { ExtractionRun } from "./gen/bgvoice/v1/pipeline_pb";
import {
  formatTimestamp,
  runKindLabel,
  runStatusLabel,
  toNumber,
} from "./pipeline-labels";
import { StatusPill } from "./resource-ui";

type RunOrder = "started_at" | "completed_at" | "run_kind" | "status";

const COLUMNS = [
  {
    label: "Stage",
    orderBy: "run_kind",
    render: (run) => (
      <div className="definition-name">
        <strong>{runKindLabel(run.runKind)}</strong>
        <span className="mono">{run.runId}</span>
      </div>
    ),
  },
  { label: "Started", orderBy: "started_at", render: (run) => formatTimestamp(run.startedAt) },
  { label: "Completed", orderBy: "completed_at", render: (run) => formatTimestamp(run.completedAt) },
  {
    label: "Extracted",
    numeric: true,
    render: (run) => `${formatCount(toNumber(run.detailsExtracted))} / ${formatCount(toNumber(run.resourcesDiscovered))}`,
  },
  { label: "Failures", numeric: true, render: (run) => formatCount(toNumber(run.failures)) },
  {
    label: "Status",
    orderBy: "status",
    render: (run) => <StatusPill value={runStatusLabel(run.status)} />,
  },
] satisfies readonly Column<ExtractionRun, RunOrder>[];

export function ExtractionRunsPage() {
  return (
    <TableBrowser
      defaultOrderBy="started_at desc"
      loadPage={listExtractionRuns}
      columns={COLUMNS}
      rowKey={(run) => run.name}
      eyebrow="HISTORY"
      title="Extraction runs"
      description="Each source extraction stage attempt, newest first."
      noun="runs"
      searchPlaceholder="Search run IDs and stages…"
      className="runs-browser"
    />
  );
}
