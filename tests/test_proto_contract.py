"""Cross-generator checks for the shared Protobuf service contract."""

import json
from datetime import UTC, datetime

from google.protobuf.json_format import MessageToDict

from bgvoice.v1 import pipeline_connect, pipeline_pb2, pipeline_pydantic


def test_pydantic_models_round_trip_standard_proto_json() -> None:
    wire = pipeline_pb2.ExtractionRun(
        name="installations/bg2ee-eet/extractionRuns/run-example",
        run_id="example",
        run_kind=pipeline_pb2.RUN_KIND_DIALOGUES,
        started_at=datetime(2026, 8, 27, tzinfo=UTC),
        status=pipeline_pb2.RUN_STATUS_COMPLETE,
        resources_discovered=4,
    )
    proto_json = MessageToDict(wire)

    model = pipeline_pydantic.ExtractionRun.model_validate(proto_json)

    assert json.loads(model.model_dump_json()) == proto_json
    assert model.run_kind == "RUN_KIND_DIALOGUES"
    assert model.started_at == datetime(2026, 8, 27, tzinfo=UTC)


def test_generated_connect_service_exposes_resource_methods() -> None:
    endpoints = pipeline_connect.PipelineServiceASGIApplication
    method_names = pipeline_pb2.DESCRIPTOR.services_by_name["PipelineService"].methods_by_name

    assert endpoints is not None
    assert {"GetVoice", "ListVoices", "GetDialogue", "DownloadPortrait"} <= set(method_names)
