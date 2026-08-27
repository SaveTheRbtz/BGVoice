"""Validated DLG projections, lines, transitions, and extraction results."""

from collections import Counter
from typing import Literal, Self

from pydantic import Field, model_validator

from bgvoice.model_types import (
    DialogueLineKind,
    DialogueToken,
    IeCliProjection,
    ResRef,
    StrictModel,
    StringReference,
    UInt32,
    WireResRef,
    compose_search_text,
    dialogue_tokens,
    optional_resref,
)


class DlgTransitionFlags(IeCliProjection):
    """Raw DLG transition flags and ie-cli's human-readable decoding."""

    raw: UInt32
    decoded: list[str]


class DlgTransition(IeCliProjection):
    """One DLG V1 transition, including its conditions, actions, and destination."""

    index: UInt32
    flags: DlgTransitionFlags
    player_text: StringReference | None = None
    journal_text: StringReference | None = None
    trigger_index: UInt32 | None = None
    trigger_text: str | None = None
    action_index: UInt32 | None = None
    action_text: str | None = None
    next_dialog: WireResRef | None = None
    next_state_index: UInt32 | None = None
    terminates_dialog: bool

    @model_validator(mode="after")
    def validate_optional_fields(self) -> Self:
        assert self.trigger_text is None or self.trigger_index is not None, (
            "DLG transition trigger text requires a trigger index"
        )
        assert self.action_text is None or self.action_index is not None, (
            "DLG transition action text requires an action index"
        )
        assert (self.next_state_index is None) == self.terminates_dialog, (
            "DLG transition must terminate exactly when it has no destination state"
        )
        return self


class DlgState(IeCliProjection):
    """One DLG V1 actor-response state and its outgoing player transitions."""

    index: UInt32
    first_transition_index: UInt32
    num_transitions: UInt32
    response_text: StringReference
    trigger_index: UInt32 | None = None
    trigger_text: str | None = None
    transitions: list[DlgTransition]

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        assert self.trigger_text is None or self.trigger_index is not None, (
            "DLG state trigger text requires a trigger index"
        )
        assert len(self.transitions) == self.num_transitions, (
            f"DLG state declares {self.num_transitions} transitions; "
            f"decoded {len(self.transitions)}"
        )
        assert all(
            transition.index == self.first_transition_index + offset
            for offset, transition in enumerate(self.transitions)
        ), "DLG state transitions must be contiguous from first_transition_index"
        return self


class DlgHeader(IeCliProjection):
    """DLG V1 table counts reported by ``ie-cli`` from header offsets 0x008 and 0x010."""

    num_states: UInt32
    num_transitions: UInt32


class DlgDump(IeCliProjection):
    """Voice-relevant fields parsed from ``iecli dump`` DLG JSON."""

    resource_name: str = Field(min_length=1)
    resource_type: Literal["DLG"]
    version: Literal["V1.0"]
    header: DlgHeader
    states: list[DlgState]

    @model_validator(mode="after")
    def validate_header_counts(self) -> Self:
        """Reject a partial or internally inconsistent decoded DLG."""
        assert len(self.states) == self.header.num_states, (
            f"DLG header declares {self.header.num_states} states; decoded {len(self.states)}"
        )
        transition_count = sum(len(state.transitions) for state in self.states)
        assert transition_count == self.header.num_transitions, (
            f"DLG header declares {self.header.num_transitions} transitions; "
            f"decoded {transition_count}"
        )
        return self


class DialogueDetail(StrictModel):
    """Normalized, sortable metrics for one DLG resource."""

    dlg_version: str
    state_count: UInt32
    transition_count: UInt32
    npc_line_count: int = Field(ge=0)
    player_line_count: int = Field(ge=0)
    journal_line_count: int = Field(ge=0)
    dialogue_line_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        assert self.npc_line_count == self.state_count, (
            "DLG state count must equal its NPC line count"
        )
        assert self.dialogue_line_count == self.npc_line_count + self.player_line_count, (
            "DLG spoken line count must equal NPC plus player lines"
        )
        return self

    @classmethod
    def from_dump(cls, dump: DlgDump) -> Self:
        """Count spoken and journal text while retaining header consistency."""
        player_lines = sum(
            transition.player_text is not None
            for state in dump.states
            for transition in state.transitions
        )
        journal_lines = sum(
            transition.journal_text is not None
            for state in dump.states
            for transition in state.transitions
        )
        npc_lines = len(dump.states)
        return cls(
            dlg_version=dump.version,
            state_count=dump.header.num_states,
            transition_count=dump.header.num_transitions,
            npc_line_count=npc_lines,
            player_line_count=player_lines,
            journal_line_count=journal_lines,
            dialogue_line_count=npc_lines + player_lines,
        )


class DialogueLine(StrictModel):
    """One actor, player, or journal strref extracted from a validated DLG."""

    dialogue_resource_name: str
    line_kind: DialogueLineKind
    state_index: UInt32
    state_trigger_index: UInt32 | None
    state_trigger_text: str | None
    transition_index: UInt32 | None = None
    strref: UInt32
    text: str | None
    tokens: list[DialogueToken]

    @model_validator(mode="after")
    def validate_state_trigger(self) -> Self:
        assert self.state_trigger_text is None or self.state_trigger_index is not None, (
            "DLG line state trigger text requires a trigger index"
        )
        assert self.line_kind is DialogueLineKind.NPC or self.state_trigger_index is None, (
            "only NPC state rows carry DLG state triggers"
        )
        return self

    @staticmethod
    def id_for(
        dialogue_resource_name: str,
        line_kind: DialogueLineKind,
        state_index: int,
        transition_index: int | None,
    ) -> str:
        transition = "-" if transition_index is None else str(transition_index)
        return f"{dialogue_resource_name.upper()}:{line_kind.value}:{state_index}:{transition}"

    @property
    def id(self) -> str:
        return self.id_for(
            self.dialogue_resource_name,
            self.line_kind,
            self.state_index,
            self.transition_index,
        )

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.dialogue_resource_name,
            self.text,
            self.state_trigger_text,
            *self.tokens,
        )

    @classmethod
    def from_dump(cls, dump: DlgDump) -> list[Self]:
        """Flatten DLG states and transitions into stable line-level records."""
        lines: list[Self] = []
        for state in dump.states:
            lines.append(
                cls(
                    dialogue_resource_name=dump.resource_name,
                    line_kind=DialogueLineKind.NPC,
                    state_index=state.index,
                    state_trigger_index=state.trigger_index,
                    state_trigger_text=state.trigger_text,
                    transition_index=None,
                    strref=state.response_text.strref,
                    text=state.response_text.text,
                    tokens=dialogue_tokens(state.response_text.text),
                )
            )
            for transition in state.transitions:
                for kind, reference in (
                    (DialogueLineKind.PLAYER, transition.player_text),
                    (DialogueLineKind.JOURNAL, transition.journal_text),
                ):
                    if reference is not None:
                        lines.append(
                            cls(
                                dialogue_resource_name=dump.resource_name,
                                line_kind=kind,
                                state_index=state.index,
                                state_trigger_index=None,
                                state_trigger_text=None,
                                transition_index=transition.index,
                                strref=reference.strref,
                                text=reference.text,
                                tokens=dialogue_tokens(reference.text),
                            )
                        )
        return lines


class DialogueTransitionEdge(StrictModel):
    """One flattened, addressable edge in a DLG state machine."""

    dialogue_resource_name: str = Field(min_length=1)
    state_index: UInt32
    transition_index: UInt32
    flags_raw: UInt32
    flags_decoded: list[str]
    trigger_index: UInt32 | None
    trigger_text: str | None
    action_index: UInt32 | None
    action_text: str | None
    next_dialog: ResRef | None
    next_state_index: UInt32 | None
    terminates_dialog: bool

    @model_validator(mode="after")
    def validate_optional_fields(self) -> Self:
        assert self.trigger_text is None or self.trigger_index is not None, (
            "DLG transition trigger text requires a trigger index"
        )
        assert self.action_text is None or self.action_index is not None, (
            "DLG transition action text requires an action index"
        )
        assert (self.next_state_index is None) == self.terminates_dialog, (
            "DLG transition must terminate exactly when it has no destination state"
        )
        return self

    @staticmethod
    def id_for(
        dialogue_resource_name: str,
        state_index: int,
        transition_index: int,
    ) -> str:
        return f"{dialogue_resource_name.upper()}:{state_index}:{transition_index}"

    @property
    def id(self) -> str:
        return self.id_for(
            self.dialogue_resource_name,
            self.state_index,
            self.transition_index,
        )

    @property
    def search_text(self) -> str:
        return compose_search_text(
            self.dialogue_resource_name,
            self.trigger_text,
            self.action_text,
            self.next_dialog,
            *self.flags_decoded,
        )

    @classmethod
    def from_dump(cls, dump: DlgDump) -> list[Self]:
        """Flatten transition topology without discarding conditions or actions."""
        return [
            cls(
                dialogue_resource_name=dump.resource_name,
                state_index=state.index,
                transition_index=transition.index,
                flags_raw=transition.flags.raw,
                flags_decoded=transition.flags.decoded,
                trigger_index=transition.trigger_index,
                trigger_text=transition.trigger_text,
                action_index=transition.action_index,
                action_text=transition.action_text,
                next_dialog=optional_resref(transition.next_dialog),
                next_state_index=transition.next_state_index,
                terminates_dialog=transition.terminates_dialog,
            )
            for state in dump.states
            for transition in state.transitions
        ]


class DialogueExtraction(StrictModel):
    """One DLG's aggregate metrics and addressable line records."""

    resource_name: str = Field(min_length=1)
    detail: DialogueDetail
    lines: list[DialogueLine]
    edges: list[DialogueTransitionEdge]
    serialized_size: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_line_resources(self) -> Self:
        unexpected = sorted(
            {
                line.dialogue_resource_name
                for line in self.lines
                if line.dialogue_resource_name.casefold() != self.resource_name.casefold()
            }
        )
        assert not unexpected, (
            f"DLG extraction {self.resource_name!r} contains lines for {unexpected}"
        )
        counts = Counter(line.line_kind for line in self.lines)
        expected: dict[DialogueLineKind, int] = {
            DialogueLineKind.NPC: self.detail.npc_line_count,
            DialogueLineKind.PLAYER: self.detail.player_line_count,
            DialogueLineKind.JOURNAL: self.detail.journal_line_count,
        }
        assert all(counts[kind] == count for kind, count in expected.items()), (
            f"DLG extraction {self.resource_name!r} line counts are "
            f"{dict(counts)}; expected {expected}"
        )
        assert len(self.edges) == self.detail.transition_count, (
            f"DLG extraction {self.resource_name!r} contains {len(self.edges)} edges; "
            f"expected {self.detail.transition_count}"
        )
        unexpected_edges = sorted(
            {
                edge.dialogue_resource_name
                for edge in self.edges
                if edge.dialogue_resource_name.casefold() != self.resource_name.casefold()
            }
        )
        assert not unexpected_edges, (
            f"DLG extraction {self.resource_name!r} contains edges for {unexpected_edges}"
        )
        return self

    @classmethod
    def from_dump(cls, dump: DlgDump) -> Self:
        return cls(
            resource_name=dump.resource_name,
            detail=DialogueDetail.from_dump(dump),
            lines=DialogueLine.from_dump(dump),
            edges=DialogueTransitionEdge.from_dump(dump),
            serialized_size=len(dump.model_dump_json().encode("utf-8")),
        )
