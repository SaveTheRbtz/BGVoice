"""Resource-oriented Connect service over the typed pipeline reader."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, cast

from connectrpc.code import Code
from connectrpc.errors import ConnectError

from bgvoice.model_types import (
    AttributionStatus,
    DetailStatus,
    DialogueLineKind,
    IdentifierKind,
    SourceKind,
)
from bgvoice.reader import PipelineReader
from bgvoice.reader_models import (
    CharacterQuery,
    CharacterRow,
    ClassQuery,
    ClassRow,
    DialogueLineRow,
    DialogueQuery,
    DialogueRow,
    IdentifierQuery,
    IdentifierRow,
    KitQuery,
    KitRow,
    LineQuery,
    RaceQuery,
    RaceRow,
    SoundQuery,
    SoundRow,
    TransitionQuery,
    TransitionRow,
    VoiceQuery,
    VoiceRow,
)
from bgvoice.storage_records import (
    CharacterRecord,
    DialogueRecord,
    ExtractionRunRecord,
)
from bgvoice.v1 import pipeline_connect
from bgvoice.v1 import pipeline_pb2 as pb
from bgvoice.web_contract import (
    INSTALLATION_NAME,
    Collection,
    decode_page_token,
)
from bgvoice.web_query import (
    CHARACTER_ORDER,
    CLASS_ORDER,
    DEFAULT_PAGE_SIZE,
    DIALOGUE_ORDER,
    IDENTIFIER_ORDER,
    KIT_ORDER,
    LINE_ORDER,
    MAX_PAGE_SIZE,
    RACE_ORDER,
    READER_PAGE_SIZE,
    SOUND_ORDER,
    TRANSITION_ORDER,
    VOICE_ORDER,
    Filter,
    ListPage,
    ReaderPage,
    all_rows,
    next_token,
    parse_order,
    read_window,
    resource_key,
    resource_record,
)
from bgvoice.web_resources import (
    attribution_publication,
    biography_sounds,
    character,
    character_class,
    dialogue,
    dialogue_line,
    extraction_run,
    identifier,
    kit,
    load_portrait_resrefs,
    optional_value,
    race,
    resolved_character_row,
    resolved_dialogue_row,
    selected_characters,
    selected_dialogues,
    selected_dialogues_by_resref,
    sound,
    timestamp,
    transition,
    voice,
)

if TYPE_CHECKING:
    from connectrpc.request import RequestContext


def _invalid_arguments[**P, R](
    method: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    @wraps(method)
    async def checked(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await method(*args, **kwargs)
        except ConnectError:
            raise
        except (AssertionError, ValueError) as error:
            raise ConnectError(Code.INVALID_ARGUMENT, str(error)) from error

    return checked


@dataclass(slots=True)
class PipelineService(pipeline_connect.PipelineService):
    """AIP-shaped read service backed by the current application reader."""

    reader: Callable[[], PipelineReader]

    def _page(
        self,
        collection: Collection,
        *,
        parent: str,
        page_size: int,
        page_token: str,
        request_filter: str,
        order_by: str,
    ) -> ListPage:
        assert parent == INSTALLATION_NAME, f"parent must be {INSTALLATION_NAME!r}"
        assert page_size >= 0, "page_size must not be negative"
        size = min(page_size or DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
        offset = 0
        if page_token:
            offset = decode_page_token(
                page_token,
                collection,
                filter=request_filter,
                order_by=order_by,
            )
        return ListPage(size=size, offset=offset)

    @_invalid_arguments
    async def get_installation(
        self,
        request: pb.GetInstallationRequest,
        _ctx: RequestContext[pb.GetInstallationRequest, pb.Installation],
    ) -> pb.Installation:
        if request.name != INSTALLATION_NAME:
            raise ConnectError(Code.NOT_FOUND, f"resource not found: {request.name}")
        reader = self.reader()
        stats = await reader.stats()

        message = pb.Installation(
            name=INSTALLATION_NAME,
            display_name="Baldur's Gate II: Enhanced Edition — EET",
            database_path=stats.database_path,
            database_size=stats.database_size,
            attribution_publication=attribution_publication(stats.attribution_publication),
            attribution_completed_at=(
                timestamp(stats.attribution_completed_at)
                if stats.attribution_completed_at is not None
                else None
            ),
            summary=pb.PipelineSummary(
                voices=stats.voices_total,
                characters=stats.characters_total,
                dialogues=stats.dialogues_total,
                npc_lines=stats.npc_lines,
                player_lines=stats.player_lines,
                journal_lines=stats.journal_lines,
                character_sounds=stats.character_sounds_total,
                dialogue_transitions=stats.transition_edges_total,
                races=stats.races_total,
                character_classes=stats.classes_total,
                kits=stats.kits_total,
                identifier_definitions=stats.identifiers_total,
                matched_characters=stats.characters_matched,
                partially_matched_characters=stats.characters_partially_matched,
                missing_dialogue_characters=stats.characters_missing_dialogue,
                unattributed_dialogues=stats.dialogues_unattributed,
                unattributed_dialogue_lines=stats.unattributed_dialogue_lines,
                generated_voices=stats.generated_voices,
                unique_inworld_voices=stats.unique_inworld_voices,
                directed_lines=stats.directed_lines,
                generated_audios=stats.generated_audios,
                running_tts_batches=stats.running_tts_batches,
                failed_tts_batches=stats.failed_tts_batches,
                voice_creation_failures=stats.voice_creation_failures,
                dialogue_direction_failures=stats.dialogue_direction_failures,
                audio_generation_failures=stats.audio_generation_failures,
            ),
        )
        return message

    @_invalid_arguments
    async def list_voices(
        self,
        request: pb.ListVoicesRequest,
        _ctx: RequestContext[pb.ListVoicesRequest, pb.ListVoicesResponse],
    ) -> pb.ListVoicesResponse:
        page = self._page(
            Collection.VOICES,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
        )
        filters = Filter.parse(request.filter)
        filters.finish()
        sort, direction = parse_order(request.order_by, VOICE_ORDER)
        query = VoiceQuery(q=filters.search, sort=sort, direction=direction)

        async def load(page_number: int) -> ReaderPage[VoiceRow]:
            return await self.reader().voices(
                query.model_copy(update={"page": page_number, "page_size": READER_PAGE_SIZE})
            )

        rows, total = await read_window(page.offset, page.size, load)
        reader = self.reader()
        character_names = [name for row in rows for name in row.variant_resource_names]
        dialogue_resrefs = [resref for row in rows for resref in row.dialogue_resrefs]
        characters, portrait_resrefs, attribution, dialogue_records = await asyncio.gather(
            selected_characters(reader, character_names),
            load_portrait_resrefs(reader),
            reader.attribution_snapshot(),
            selected_dialogues_by_resref(reader, dialogue_resrefs),
        )
        dialogues = {record.resource_name.casefold(): record for record in dialogue_records}
        voice_records = {record.voice_id: record for record in attribution.voices}
        return pb.ListVoicesResponse(
            voices=[
                voice(
                    row,
                    characters,
                    portrait_resrefs,
                    attribution.by_character,
                    dialogues,
                    voice_records[row.id].biography_sound_id,
                )
                for row in rows
            ],
            next_page_token=next_token(
                Collection.VOICES,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_voice(
        self,
        request: pb.GetVoiceRequest,
        _ctx: RequestContext[pb.GetVoiceRequest, pb.Voice],
    ) -> pb.Voice:
        reader = self.reader()
        voice_id = await resource_key(
            reader.voices_table,
            "voice_id",
            Collection.VOICES,
            request.name,
        )
        voice_page = await reader.voices(VoiceQuery(voice_id=voice_id, page_size=10))
        if not voice_page.items:
            raise ConnectError(Code.NOT_FOUND, f"resource not found: {request.name}")
        assert len(voice_page.items) == 1, f"duplicate current voice id: {voice_id!r}"
        row = voice_page.items[0]
        characters, portrait_resrefs, attribution, dialogue_records = await asyncio.gather(
            selected_characters(reader, row.variant_resource_names),
            load_portrait_resrefs(reader),
            reader.attribution_snapshot(),
            selected_dialogues_by_resref(reader, row.dialogue_resrefs),
        )
        return voice(
            row,
            characters,
            portrait_resrefs,
            attribution.by_character,
            {record.resource_name.casefold(): record for record in dialogue_records},
            next(
                record.biography_sound_id
                for record in attribution.voices
                if record.voice_id == row.id
            ),
        )

    @_invalid_arguments
    async def list_characters(
        self,
        request: pb.ListCharactersRequest,
        _ctx: RequestContext[pb.ListCharactersRequest, pb.ListCharactersResponse],
    ) -> pb.ListCharactersResponse:
        page = self._page(
            Collection.CHARACTERS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
        )
        filters = Filter.parse(request.filter)
        sort, direction = parse_order(request.order_by, CHARACTER_ORDER)
        query = CharacterQuery(
            q=filters.search,
            status=filters.enum("detail_status", DetailStatus),
            source_kind=filters.enum("source_kind", SourceKind),
            gender_id=filters.integer("gender_id"),
            race_id=filters.integer("race_id"),
            class_id=filters.integer("class_id"),
            attribution_status=filters.enum("attribution_status", AttributionStatus),
            sort=sort,
            direction=direction,
        )
        filters.finish()

        async def load(page_number: int) -> ReaderPage[CharacterRow]:
            return await self.reader().characters(
                query.model_copy(update={"page": page_number, "page_size": READER_PAGE_SIZE})
            )

        rows, total = await read_window(page.offset, page.size, load)
        reader = self.reader()
        character_names = [row.resource_name for row in rows]
        records, portrait_resrefs, biographies = await asyncio.gather(
            selected_characters(reader, character_names),
            load_portrait_resrefs(reader),
            biography_sounds(reader, character_names),
        )
        return pb.ListCharactersResponse(
            characters=[
                character(
                    row,
                    records[row.resource_name],
                    portrait_resrefs,
                    optional_value(biographies, row.resource_name),
                )
                for row in rows
            ],
            next_page_token=next_token(
                Collection.CHARACTERS,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_character(
        self,
        request: pb.GetCharacterRequest,
        _ctx: RequestContext[pb.GetCharacterRequest, pb.Character],
    ) -> pb.Character:
        reader = self.reader()
        record = await resource_record(
            reader.characters_table,
            CharacterRecord,
            "resource_name",
            Collection.CHARACTERS,
            request.name,
        )
        row, portrait_resrefs, biographies = await asyncio.gather(
            resolved_character_row(reader, record),
            load_portrait_resrefs(reader),
            biography_sounds(reader, [record.resource_name]),
        )
        return character(
            row,
            record,
            portrait_resrefs,
            optional_value(biographies, record.resource_name),
        )

    @_invalid_arguments
    async def list_dialogues(
        self,
        request: pb.ListDialoguesRequest,
        _ctx: RequestContext[pb.ListDialoguesRequest, pb.ListDialoguesResponse],
    ) -> pb.ListDialoguesResponse:
        page = self._page(
            Collection.DIALOGUES,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
        )
        filters = Filter.parse(request.filter)
        sort, direction = parse_order(request.order_by, DIALOGUE_ORDER)
        query = DialogueQuery(
            q=filters.search,
            status=filters.enum("detail_status", DetailStatus),
            source_kind=filters.enum("source_kind", SourceKind),
            attributed=filters.boolean("attributed"),
            sort=sort,
            direction=direction,
        )
        filters.finish()

        async def load(page_number: int) -> ReaderPage[DialogueRow]:
            return await self.reader().dialogues(
                query.model_copy(update={"page": page_number, "page_size": READER_PAGE_SIZE})
            )

        rows, total = await read_window(page.offset, page.size, load)
        records = await selected_dialogues(self.reader(), [row.resource_name for row in rows])
        return pb.ListDialoguesResponse(
            dialogues=[dialogue(row, records[row.resource_name]) for row in rows],
            next_page_token=next_token(
                Collection.DIALOGUES,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def get_dialogue(
        self,
        request: pb.GetDialogueRequest,
        _ctx: RequestContext[pb.GetDialogueRequest, pb.Dialogue],
    ) -> pb.Dialogue:
        reader = self.reader()
        record = await resource_record(
            reader.dialogues_table,
            DialogueRecord,
            "resource_name",
            Collection.DIALOGUES,
            request.name,
        )
        row = await resolved_dialogue_row(reader, record)
        return dialogue(row, record)

    @_invalid_arguments
    async def list_dialogue_lines(
        self,
        request: pb.ListDialogueLinesRequest,
        _ctx: RequestContext[pb.ListDialogueLinesRequest, pb.ListDialogueLinesResponse],
    ) -> pb.ListDialogueLinesResponse:
        page = self._page(
            Collection.DIALOGUE_LINES,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
        )
        filters = Filter.parse(request.filter)
        sort, direction = parse_order(request.order_by, LINE_ORDER)
        query = LineQuery(
            q=filters.search,
            line_kind=filters.enum("line_kind", DialogueLineKind),
            source_kind=filters.enum("source_kind", SourceKind),
            attributed=filters.boolean("attributed"),
            dialogue_resource_name=filters.text("dialogue_resource_name"),
            voice_id=filters.text("voice_id"),
            directed=filters.boolean("directed"),
            voiced=filters.boolean("voiced"),
            sort=sort,
            direction=direction,
        )
        filters.finish()

        async def load(page_number: int) -> ReaderPage[DialogueLineRow]:
            return await self.reader().lines(
                query.model_copy(update={"page": page_number, "page_size": READER_PAGE_SIZE})
            )

        rows, total = await read_window(page.offset, page.size, load)
        return pb.ListDialogueLinesResponse(
            dialogue_lines=[dialogue_line(row) for row in rows],
            next_page_token=next_token(
                Collection.DIALOGUE_LINES,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def list_character_sounds(
        self,
        request: pb.ListCharacterSoundsRequest,
        _ctx: RequestContext[pb.ListCharacterSoundsRequest, pb.ListCharacterSoundsResponse],
    ) -> pb.ListCharacterSoundsResponse:
        page = self._page(
            Collection.CHARACTER_SOUNDS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
        )
        filters = Filter.parse(request.filter)
        sort, direction = parse_order(request.order_by, SOUND_ORDER)
        query = SoundQuery(
            q=filters.search,
            slot_id=filters.integer("slot_id"),
            sort=sort,
            direction=direction,
        )
        filters.finish()

        async def load(page_number: int) -> ReaderPage[SoundRow]:
            return await self.reader().sounds(
                query.model_copy(update={"page": page_number, "page_size": READER_PAGE_SIZE})
            )

        rows, total = await read_window(page.offset, page.size, load)
        return pb.ListCharacterSoundsResponse(
            character_sounds=[sound(row) for row in rows],
            next_page_token=next_token(
                Collection.CHARACTER_SOUNDS,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def list_dialogue_transitions(
        self,
        request: pb.ListDialogueTransitionsRequest,
        _ctx: RequestContext[
            pb.ListDialogueTransitionsRequest,
            pb.ListDialogueTransitionsResponse,
        ],
    ) -> pb.ListDialogueTransitionsResponse:
        page = self._page(
            Collection.DIALOGUE_TRANSITIONS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
        )
        filters = Filter.parse(request.filter)
        sort, direction = parse_order(request.order_by, TRANSITION_ORDER)
        query = TransitionQuery(
            q=filters.search,
            dialogue_resource_name=filters.text("dialogue_resource_name"),
            terminates_dialog=filters.boolean("terminates_dialog"),
            sort=sort,
            direction=direction,
        )
        filters.finish()

        async def load(page_number: int) -> ReaderPage[TransitionRow]:
            return await self.reader().transitions(
                query.model_copy(update={"page": page_number, "page_size": READER_PAGE_SIZE})
            )

        rows, total = await read_window(page.offset, page.size, load)
        return pb.ListDialogueTransitionsResponse(
            dialogue_transitions=[transition(row) for row in rows],
            next_page_token=next_token(
                Collection.DIALOGUE_TRANSITIONS,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def list_races(
        self,
        request: pb.ListRacesRequest,
        _ctx: RequestContext[pb.ListRacesRequest, pb.ListRacesResponse],
    ) -> pb.ListRacesResponse:
        page = self._page(
            Collection.RACES,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
        )
        filters = Filter.parse(request.filter)
        sort, direction = parse_order(request.order_by, RACE_ORDER)
        query = RaceQuery(
            q=filters.search,
            campaign=filters.text("campaign"),
            sort=sort,
            direction=direction if sort is not None else "asc",
        )
        filters.finish()

        async def load(page_number: int) -> ReaderPage[RaceRow]:
            return await self.reader().races(
                query.model_copy(update={"page": page_number, "page_size": READER_PAGE_SIZE})
            )

        source_rows = await all_rows(load)
        resources = _groups(source_rows, lambda row: row.race_id)
        if sort is not None or filters.search is None:
            field = sort or "race_id"
            if field == "race_id":
                resources.sort(key=lambda rows: rows[0].race_id, reverse=direction == "desc")
            elif field == "name":
                resources.sort(
                    key=lambda rows: next(
                        (row.name.casefold() for row in rows if row.name is not None),
                        "",
                    ),
                    reverse=direction == "desc",
                )
            else:
                resources.sort(
                    key=lambda rows: next(
                        (
                            row.source_resource.casefold()
                            for row in rows
                            if row.source_resource is not None
                        ),
                        "",
                    ),
                    reverse=direction == "desc",
                )
        total = len(resources)
        selected = resources[page.offset : page.offset + page.size]
        return pb.ListRacesResponse(
            races=[race(rows) for rows in selected],
            next_page_token=next_token(
                Collection.RACES,
                request.filter,
                request.order_by,
                page,
                len(selected),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def list_character_classes(
        self,
        request: pb.ListCharacterClassesRequest,
        _ctx: RequestContext[
            pb.ListCharacterClassesRequest,
            pb.ListCharacterClassesResponse,
        ],
    ) -> pb.ListCharacterClassesResponse:
        page = self._page(
            Collection.CHARACTER_CLASSES,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
        )
        filters = Filter.parse(request.filter)
        sort, direction = parse_order(request.order_by, CLASS_ORDER)
        query = ClassQuery(
            q=filters.search,
            campaign=filters.text("campaign"),
            class_id=filters.integer("class_id"),
            fallen=filters.boolean("fallen"),
            sort=sort,
            direction=direction if sort is not None else "asc",
        )
        filters.finish()

        async def load(page_number: int) -> ReaderPage[ClassRow]:
            return await self.reader().classes(
                query.model_copy(update={"page": page_number, "page_size": READER_PAGE_SIZE})
            )

        source_rows = await all_rows(load)
        resources = _groups(source_rows, lambda row: row.class_id)
        if sort is not None or filters.search is None:
            field = sort or "class_id"
            if field == "class_id":
                resources.sort(key=lambda rows: rows[0].class_id, reverse=direction == "desc")
            elif field == "lower_name":
                resources.sort(
                    key=lambda rows: next(
                        (
                            (row.mixed_name or row.lower_name or "").casefold()
                            for row in rows
                            if row.mixed_name is not None or row.lower_name is not None
                        ),
                        "",
                    ),
                    reverse=direction == "desc",
                )
            else:
                resources.sort(
                    key=lambda rows: any(row.fallen is True for row in rows),
                    reverse=direction == "desc",
                )
        total = len(resources)
        selected = resources[page.offset : page.offset + page.size]
        return pb.ListCharacterClassesResponse(
            character_classes=[character_class(rows) for rows in selected],
            next_page_token=next_token(
                Collection.CHARACTER_CLASSES,
                request.filter,
                request.order_by,
                page,
                len(selected),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def list_kits(
        self,
        request: pb.ListKitsRequest,
        _ctx: RequestContext[pb.ListKitsRequest, pb.ListKitsResponse],
    ) -> pb.ListKitsResponse:
        page = self._page(
            Collection.KITS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
        )
        filters = Filter.parse(request.filter)
        sort, direction = parse_order(request.order_by, KIT_ORDER)
        query = KitQuery(
            q=filters.search,
            class_id=filters.integer("class_id"),
            sort=sort,
            direction=direction if sort is not None else "asc",
        )
        filters.finish()

        async def load(page_number: int) -> ReaderPage[KitRow]:
            return await self.reader().kits(
                query.model_copy(update={"page": page_number, "page_size": READER_PAGE_SIZE})
            )

        rows, total = await read_window(page.offset, page.size, load)
        return pb.ListKitsResponse(
            kits=[kit(row) for row in rows],
            next_page_token=next_token(
                Collection.KITS,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def list_identifier_definitions(
        self,
        request: pb.ListIdentifierDefinitionsRequest,
        _ctx: RequestContext[
            pb.ListIdentifierDefinitionsRequest,
            pb.ListIdentifierDefinitionsResponse,
        ],
    ) -> pb.ListIdentifierDefinitionsResponse:
        page = self._page(
            Collection.IDENTIFIER_DEFINITIONS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
        )
        filters = Filter.parse(request.filter)
        display_order = request.order_by == "display_name" or request.order_by.startswith(
            "display_name "
        )
        if display_order:
            _, direction = parse_order(request.order_by, {"display_name": "display_name"})
            sort = None
        else:
            sort, direction = parse_order(request.order_by, IDENTIFIER_ORDER)
        identifier_kind = filters.enum("kind", IdentifierKind)
        assert identifier_kind not in {
            IdentifierKind.RACE,
            IdentifierKind.CLASS,
            IdentifierKind.KIT,
        }, "kind must name a simple identifier definition"
        query = IdentifierQuery(
            q=filters.search,
            kind=identifier_kind,
            sort=sort,
            direction=direction if sort is not None else "asc",
        )
        filters.finish()

        async def load(page_number: int) -> ReaderPage[IdentifierRow]:
            return await self.reader().identifiers(
                query.model_copy(update={"page": page_number, "page_size": READER_PAGE_SIZE})
            )

        if display_order:
            sorted_rows = await all_rows(load)
            sorted_rows.sort(
                key=lambda row: identifier(row).display_name.casefold(),
                reverse=direction == "desc",
            )
            total = len(sorted_rows)
            rows = sorted_rows[page.offset : page.offset + page.size]
        else:
            rows, total = await read_window(page.offset, page.size, load)
        return pb.ListIdentifierDefinitionsResponse(
            identifier_definitions=[identifier(row) for row in rows],
            next_page_token=next_token(
                Collection.IDENTIFIER_DEFINITIONS,
                request.filter,
                request.order_by,
                page,
                len(rows),
                total,
            ),
            total_size=total,
        )

    @_invalid_arguments
    async def list_extraction_runs(
        self,
        request: pb.ListExtractionRunsRequest,
        _ctx: RequestContext[
            pb.ListExtractionRunsRequest,
            pb.ListExtractionRunsResponse,
        ],
    ) -> pb.ListExtractionRunsResponse:
        page = self._page(
            Collection.EXTRACTION_RUNS,
            parent=request.parent,
            page_size=request.page_size,
            page_token=request.page_token,
            request_filter=request.filter,
            order_by=request.order_by,
        )
        filters = Filter.parse(request.filter)
        filters.finish()
        sort, direction = parse_order(
            request.order_by,
            {
                "started_at": "started_at",
                "completed_at": "completed_at",
                "run_kind": "run_kind",
                "status": "status",
            },
        )
        runs = cast(
            list[ExtractionRunRecord],
            await self.reader().runs_table.query().to_pydantic(ExtractionRunRecord),
        )
        rows = runs
        if filters.search is not None:
            query = filters.search.casefold()
            rows = [
                row
                for row in rows
                if query in " ".join((row.id, row.run_kind, row.status, row.error or "")).casefold()
            ]
        field = sort or "started_at"
        if field == "completed_at":
            rows.sort(
                key=lambda row: row.completed_at or "",
                reverse=direction == "desc" if sort is not None else True,
            )
        else:
            rows.sort(
                key=lambda row: getattr(row, field),
                reverse=direction == "desc" if sort is not None else True,
            )
        total = len(rows)
        selected = rows[page.offset : page.offset + page.size]
        return pb.ListExtractionRunsResponse(
            extraction_runs=[extraction_run(row) for row in selected],
            next_page_token=next_token(
                Collection.EXTRACTION_RUNS,
                request.filter,
                request.order_by,
                page,
                len(selected),
                total,
            ),
            total_size=total,
        )


def _groups[Row, Key: Hashable](
    rows: list[Row],
    key: Callable[[Row], Key],
) -> list[list[Row]]:
    groups: dict[Key, list[Row]] = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    return list(groups.values())
