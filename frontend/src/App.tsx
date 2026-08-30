import { useEffect, useRef, useState } from "react";
import type { ComponentType } from "react";

import { getInstallation } from "./api";
import { ErrorBanner } from "./browser";
import { CharacterBrowser, CharacterDetailPage } from "./CharacterPages";
import { DialogueLineBrowser } from "./DialogueLines";
import { DialogueBrowser, DialogueDetailPage } from "./DialoguePages";
import { ExtractionRunsPage } from "./ExtractionRunsPage";
import { formatBytes } from "./format";
import type { Installation } from "./gen/bgvoice/v1/pipeline_pb";
import {
  ClassBrowser,
  IdentifierBrowser,
  KitBrowser,
  RaceBrowser,
} from "./MetadataBrowser";
import { PipelinePage } from "./PipelinePage";
import { ReadableItemBrowser } from "./ReadableItemBrowser";
import { toNumber } from "./pipeline-labels";
import { dialogueLinesPath, followLink, navigate, useRoute } from "./routes";
import type { AppRoute, DialogueLineKind } from "./routes";
import { SoundBrowser } from "./SoundBrowser";
import { TransitionBrowser } from "./TransitionBrowser";
import { errorMessage } from "./use-browser";
import { VoiceBrowser, VoiceDetailPage } from "./VoicePages";

interface NavigationLinkData {
  href: string;
  label: string;
  icon: string;
  route: AppRoute["name"];
  lineKind?: DialogueLineKind;
}

interface NavigationGroup {
  label: string;
  links: readonly NavigationLinkData[];
}

const NAVIGATION: readonly NavigationGroup[] = [
  {
    label: "Work",
    links: [{ href: "/voices", label: "Voices", icon: "V", route: "voices" }],
  },
  {
    label: "Dialogue",
    links: [
      { href: "/dialogues", label: "Dialogues", icon: "D", route: "dialogues" },
      { href: dialogueLinesPath(), label: "NPC lines", icon: "N", route: "dialogue-lines", lineKind: "npc" },
      { href: dialogueLinesPath({ line_kind: "player" }), label: "Player lines", icon: "P", route: "dialogue-lines", lineKind: "player" },
      { href: dialogueLinesPath({ line_kind: "journal" }), label: "Journal", icon: "J", route: "dialogue-lines", lineKind: "journal" },
      { href: "/dialogue-transitions", label: "Transitions", icon: "T", route: "dialogue-transitions" },
    ],
  },
  {
    label: "Source data",
    links: [
      { href: "/characters", label: "Characters", icon: "C", route: "characters" },
      { href: "/character-sounds", label: "Sounds", icon: "S", route: "character-sounds" },
      { href: "/readable-items", label: "Readable items", icon: "R", route: "readable-items" },
    ],
  },
  {
    label: "Definitions",
    links: [
      { href: "/definitions/races", label: "Races", icon: "R", route: "races" },
      { href: "/definitions/character-classes", label: "Classes", icon: "C", route: "character-classes" },
      { href: "/definitions/kits", label: "Kits", icon: "K", route: "kits" },
      { href: "/definitions/identifier-definitions", label: "Identifiers", icon: "I", route: "identifier-definitions" },
    ],
  },
  {
    label: "System",
    links: [
      { href: "/pipeline", label: "Pipeline", icon: "P", route: "pipeline" },
      { href: "/extraction-runs", label: "Extraction runs", icon: "R", route: "extraction-runs" },
    ],
  },
];

const ROUTE_TITLES = {
  voices: "Voices",
  characters: "Characters",
  dialogues: "Dialogues",
  "dialogue-lines": "Dialogue lines",
  "dialogue-transitions": "Transitions",
  "character-sounds": "Character sounds",
  "readable-items": "Readable items",
  races: "Races",
  "character-classes": "Character classes",
  kits: "Kits",
  "identifier-definitions": "Identifiers",
  pipeline: "Pipeline",
  "extraction-runs": "Extraction runs",
  "not-found": "Resource not found",
} satisfies Record<AppRoute["name"], string>;

const STATIC_PAGES: Partial<Record<AppRoute["name"], ComponentType>> = {
  "dialogue-transitions": TransitionBrowser,
  "character-sounds": SoundBrowser,
  "readable-items": ReadableItemBrowser,
  "extraction-runs": ExtractionRunsPage,
  races: RaceBrowser,
  "character-classes": ClassBrowser,
  kits: KitBrowser,
  "identifier-definitions": IdentifierBrowser,
};

export default function App() {
  const route = useRoute();
  const pathname = window.location.pathname;
  const pageTitle = ROUTE_TITLES[route.name];
  const [installation, setInstallation] = useState<Installation | null>(null);
  const [installationError, setInstallationError] = useState<string | null>(null);

  useEffect(() => {
    if (window.location.pathname === "/") navigate("/voices", true);
  }, []);

  useEffect(() => {
    document.title = `${pageTitle} · BGVoice`;
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
    document.getElementById("main-content")?.focus({ preventScroll: true });
  }, [pageTitle, pathname]);

  useEffect(() => {
    const controller = new AbortController();
    getInstallation(controller.signal)
      .then(setInstallation)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setInstallationError(errorMessage(reason));
      });
    return () => controller.abort();
  }, []);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <DesktopNavigation route={route} installation={installation} />
      <MobileNavigation route={route} />
      <main id="main-content" className="page-main" tabIndex={-1}>
        {installationError != null && <ErrorBanner message={installationError} />}
        <RouteContent route={route} installation={installation} />
      </main>
    </div>
  );
}

function DesktopNavigation({ route, installation }: {
  route: AppRoute;
  installation: Installation | null;
}) {
  return (
    <aside className="side-nav">
      <Brand />
      <nav aria-label="Pipeline resources">
        {NAVIGATION.map((group) => (
          <section className="nav-group" key={group.label}>
            <h2>{group.label}</h2>
            {group.links.map((link) => <NavigationLink key={link.href} link={link} route={route} />)}
          </section>
        ))}
      </nav>
      <div className="database-status">
        <span><i /> Read only</span>
        <strong>{installation?.displayName ?? "EET installation"}</strong>
        <small>{formatBytes(toNumber(installation?.databaseSize))}</small>
      </div>
    </aside>
  );
}

function MobileNavigation({ route }: { route: AppRoute }) {
  const navigation = useRef<HTMLElement>(null);
  const pathname = window.location.pathname;
  useEffect(() => {
    navigation.current
      ?.querySelector<HTMLElement>('[aria-current="page"]')
      ?.scrollIntoView?.({ block: "nearest", inline: "center" });
  }, [pathname]);

  return (
    <header className="mobile-topbar">
      <div className="mobile-topbar-head">
        <Brand />
        <span className="read-only"><i /> Read only</span>
      </div>
      <nav ref={navigation} className="mobile-nav" aria-label="Pipeline resources">
        {NAVIGATION.flatMap((group) => group.links).map((link) => (
          <NavigationLink key={link.href} link={link} route={route} compact />
        ))}
      </nav>
    </header>
  );
}

function NavigationLink({ link, route, compact = false }: {
  link: NavigationLinkData;
  route: AppRoute;
  compact?: boolean;
}) {
  const active = link.route === route.name
    && (link.lineKind == null || (route.name === "dialogue-lines" && route.lineKind === link.lineKind));
  return (
    <a
      className={active ? "is-active" : undefined}
      href={link.href}
      aria-current={active ? "page" : undefined}
      onClick={(event) => followLink(event, link.href)}
    >
      {!compact && <span aria-hidden="true">{link.icon}</span>}
      {link.label}
    </a>
  );
}

function Brand() {
  return (
    <a className="brand-lockup" href="/voices" onClick={(event) => followLink(event, "/voices")}>
      <span className="brand-mark" aria-hidden="true">B</span>
      <span>
        <strong>BGVOICE</strong>
        <small>EET voice pipeline</small>
      </span>
    </a>
  );
}

function RouteContent({ route, installation }: { route: AppRoute; installation: Installation | null }) {
  if (route.name === "voices") {
    return route.voiceName == null
      ? <VoiceBrowser />
      : <VoiceDetailPage name={route.voiceName} />;
  }
  if (route.name === "characters") {
    return route.resourceName == null
      ? <CharacterBrowser />
      : <CharacterDetailPage name={route.resourceName} />;
  }
  if (route.name === "dialogues") {
    return route.resourceName == null
      ? <DialogueBrowser />
      : <DialogueDetailPage name={route.resourceName} />;
  }
  if (route.name === "pipeline") {
    return <PipelinePage installation={installation} />;
  }
  if (route.name === "dialogue-lines") {
    return <DialogueLineBrowser key={route.lineKind} lineKind={route.lineKind} />;
  }
  const Page = STATIC_PAGES[route.name];
  return Page == null ? <NotFound /> : <Page />;
}

function NotFound() {
  const href = "/voices";
  return (
    <section className="not-found">
      <span aria-hidden="true">404</span>
      <h1>Resource not found</h1>
      <p>This route does not identify a pipeline resource.</p>
      <a href={href} onClick={(event) => followLink(event, href)}>Back to voices</a>
    </section>
  );
}
