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

function listRequest(query: ListQuery, view = View.BASIC): {
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
    view,
  };
}

function listResult<T>(
  items: T[],
  response: { nextPageToken: string; totalSize: bigint },
): ListResult<T> {
  return { items, nextPageToken: response.nextPageToken, totalSize: response.totalSize };
}

function options(signal?: AbortSignal): { signal?: AbortSignal } {
  return signal === undefined ? {} : { signal };
}

export function getInstallation(signal?: AbortSignal): Promise<Installation> {
  return client.getInstallation({ name: INSTALLATION_NAME }, options(signal));
}

export async function listVoices(
  query: ListQuery,
  signal?: AbortSignal,
): Promise<ListResult<Voice>> {
  const response = await client.listVoices(listRequest(query), options(signal));
  return listResult(response.voices, response);
}

export function getVoice(name: string, signal?: AbortSignal): Promise<Voice> {
  return client.getVoice({ name, view: View.FULL }, options(signal));
}

export async function listCharacters(
  query: ListQuery,
  signal?: AbortSignal,
): Promise<ListResult<Character>> {
  const response = await client.listCharacters(listRequest(query, View.FULL), options(signal));
  return listResult(response.characters, response);
}

export function getCharacter(name: string, signal?: AbortSignal): Promise<Character> {
  return client.getCharacter({ name, view: View.FULL }, options(signal));
}

export async function listDialogues(
  query: ListQuery,
  signal?: AbortSignal,
): Promise<ListResult<Dialogue>> {
  const response = await client.listDialogues(listRequest(query, View.FULL), options(signal));
  return listResult(response.dialogues, response);
}

export function getDialogue(name: string, signal?: AbortSignal): Promise<Dialogue> {
  return client.getDialogue({ name, view: View.FULL }, options(signal));
}

export async function listDialogueLines(
  query: ListQuery,
  signal?: AbortSignal,
): Promise<ListResult<DialogueLine>> {
  const response = await client.listDialogueLines(listRequest(query), options(signal));
  return listResult(response.dialogueLines, response);
}

export async function listCharacterSounds(
  query: ListQuery,
  signal?: AbortSignal,
): Promise<ListResult<CharacterSound>> {
  const response = await client.listCharacterSounds(listRequest(query), options(signal));
  return listResult(response.characterSounds, response);
}

export async function listDialogueTransitions(
  query: ListQuery,
  signal?: AbortSignal,
): Promise<ListResult<DialogueTransition>> {
  const response = await client.listDialogueTransitions(listRequest(query), options(signal));
  return listResult(response.dialogueTransitions, response);
}

export async function listRaces(
  query: ListQuery,
  signal?: AbortSignal,
): Promise<ListResult<Race>> {
  const response = await client.listRaces(listRequest(query, View.FULL), options(signal));
  return listResult(response.races, response);
}

export async function listCharacterClasses(
  query: ListQuery,
  signal?: AbortSignal,
): Promise<ListResult<CharacterClass>> {
  const response = await client.listCharacterClasses(listRequest(query, View.FULL), options(signal));
  return listResult(response.characterClasses, response);
}

export async function listKits(
  query: ListQuery,
  signal?: AbortSignal,
): Promise<ListResult<Kit>> {
  const response = await client.listKits(listRequest(query), options(signal));
  return listResult(response.kits, response);
}

export async function listIdentifierDefinitions(
  query: ListQuery,
  signal?: AbortSignal,
): Promise<ListResult<IdentifierDefinition>> {
  const response = await client.listIdentifierDefinitions(listRequest(query), options(signal));
  return listResult(response.identifierDefinitions, response);
}

export async function listExtractionRuns(
  query: ListQuery,
  signal?: AbortSignal,
): Promise<ListResult<ExtractionRun>> {
  const response = await client.listExtractionRuns(listRequest(query), options(signal));
  return listResult(response.extractionRuns, response);
}

export function portraitUrl(name: string): string {
  return `/v1/${name}:download`;
}
