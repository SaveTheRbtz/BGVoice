import { createClient } from "@connectrpc/connect";
import { createConnectTransport } from "@connectrpc/connect-web";

import {
  PipelineService,
  View,
  type Character,
  type CharacterClass,
  type CharacterSound,
  type Dialogue,
  type DialogueLine,
  type DialogueTransition,
  type ExtractionRun,
  type IdentifierDefinition,
  type Installation,
  type Kit,
  type Race,
  type Voice,
} from "./gen/bgvoice/v1/pipeline_pb";

export const INSTALLATION_NAME = "installations/bg2ee-eet";

export interface ListQuery {
  filter?: string;
  orderBy?: string;
  pageSize?: number;
  pageToken?: string;
  view?: View;
}

export interface ListResult<T> {
  items: T[];
  nextPageToken: string;
  totalSize: bigint;
}

const client = createClient(
  PipelineService,
  createConnectTransport({ baseUrl: "/connect" }),
);

function listRequest(query: ListQuery): {
  parent: string;
  pageSize: number;
  pageToken: string;
  filter: string;
  orderBy: string;
  view: View;
} {
  return {
    parent: INSTALLATION_NAME,
    pageSize: query.pageSize ?? 25,
    pageToken: query.pageToken ?? "",
    filter: query.filter ?? "",
    orderBy: query.orderBy ?? "",
    view: query.view ?? View.BASIC,
  };
}

function options(signal?: AbortSignal): { signal?: AbortSignal } {
  return signal === undefined ? {} : { signal };
}

export const pipelineData = {
  getInstallation(signal?: AbortSignal): Promise<Installation> {
    return client.getInstallation({ name: INSTALLATION_NAME }, options(signal));
  },

  async listVoices(query: ListQuery, signal?: AbortSignal): Promise<ListResult<Voice>> {
    const response = await client.listVoices(listRequest(query), options(signal));
    return {
      items: response.voices,
      nextPageToken: response.nextPageToken,
      totalSize: response.totalSize,
    };
  },

  getVoice(name: string, signal?: AbortSignal): Promise<Voice> {
    return client.getVoice({ name, view: View.FULL }, options(signal));
  },

  async listCharacters(
    query: ListQuery,
    signal?: AbortSignal,
  ): Promise<ListResult<Character>> {
    const response = await client.listCharacters(listRequest(query), options(signal));
    return {
      items: response.characters,
      nextPageToken: response.nextPageToken,
      totalSize: response.totalSize,
    };
  },

  getCharacter(name: string, signal?: AbortSignal): Promise<Character> {
    return client.getCharacter({ name, view: View.FULL }, options(signal));
  },

  async listDialogues(
    query: ListQuery,
    signal?: AbortSignal,
  ): Promise<ListResult<Dialogue>> {
    const response = await client.listDialogues(listRequest(query), options(signal));
    return {
      items: response.dialogues,
      nextPageToken: response.nextPageToken,
      totalSize: response.totalSize,
    };
  },

  getDialogue(name: string, signal?: AbortSignal): Promise<Dialogue> {
    return client.getDialogue({ name, view: View.FULL }, options(signal));
  },

  async listDialogueLines(
    query: ListQuery,
    signal?: AbortSignal,
  ): Promise<ListResult<DialogueLine>> {
    const response = await client.listDialogueLines(listRequest(query), options(signal));
    return {
      items: response.dialogueLines,
      nextPageToken: response.nextPageToken,
      totalSize: response.totalSize,
    };
  },

  async listCharacterSounds(
    query: ListQuery,
    signal?: AbortSignal,
  ): Promise<ListResult<CharacterSound>> {
    const response = await client.listCharacterSounds(listRequest(query), options(signal));
    return {
      items: response.characterSounds,
      nextPageToken: response.nextPageToken,
      totalSize: response.totalSize,
    };
  },

  async listDialogueTransitions(
    query: ListQuery,
    signal?: AbortSignal,
  ): Promise<ListResult<DialogueTransition>> {
    const response = await client.listDialogueTransitions(
      listRequest(query),
      options(signal),
    );
    return {
      items: response.dialogueTransitions,
      nextPageToken: response.nextPageToken,
      totalSize: response.totalSize,
    };
  },

  async listRaces(query: ListQuery, signal?: AbortSignal): Promise<ListResult<Race>> {
    const response = await client.listRaces(listRequest(query), options(signal));
    return {
      items: response.races,
      nextPageToken: response.nextPageToken,
      totalSize: response.totalSize,
    };
  },

  async listCharacterClasses(
    query: ListQuery,
    signal?: AbortSignal,
  ): Promise<ListResult<CharacterClass>> {
    const response = await client.listCharacterClasses(listRequest(query), options(signal));
    return {
      items: response.characterClasses,
      nextPageToken: response.nextPageToken,
      totalSize: response.totalSize,
    };
  },

  async listKits(query: ListQuery, signal?: AbortSignal): Promise<ListResult<Kit>> {
    const response = await client.listKits(listRequest(query), options(signal));
    return {
      items: response.kits,
      nextPageToken: response.nextPageToken,
      totalSize: response.totalSize,
    };
  },

  async listIdentifierDefinitions(
    query: ListQuery,
    signal?: AbortSignal,
  ): Promise<ListResult<IdentifierDefinition>> {
    const response = await client.listIdentifierDefinitions(
      listRequest(query),
      options(signal),
    );
    return {
      items: response.identifierDefinitions,
      nextPageToken: response.nextPageToken,
      totalSize: response.totalSize,
    };
  },

  async listExtractionRuns(
    query: ListQuery,
    signal?: AbortSignal,
  ): Promise<ListResult<ExtractionRun>> {
    const response = await client.listExtractionRuns(
      listRequest(query),
      options(signal),
    );
    return {
      items: response.extractionRuns,
      nextPageToken: response.nextPageToken,
      totalSize: response.totalSize,
    };
  },
};

export function portraitUrl(name: string): string {
  return `/v1/${name}:download`;
}
