import { useEffect, useState } from "react";
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
import { toNumber } from "./pipeline-labels";
import { followLink, navigate, useRoute } from "./routes";
import type { AppRoute } from "./routes";
import { SoundBrowser, TransitionBrowser } from "./SourceBrowsers";
import { errorMessage } from "./use-browser";
import { VoiceBrowser, VoiceDetailPage } from "./VoicePages";

interface NavigationLinkData {
  href: string;
  label: string;
  icon: string;
  routes: readonly AppRoute["name"][];
}

interface NavigationGroup {
  label: string;
  links: readonly NavigationLinkData[];
}

const NAVIGATION: readonly NavigationGroup[] = [
  {
    label: "Work",
    links: [{ href: "/voices", label: "Voices", icon: "V", routes: ["voices"] }],
  },
  {
    label: "Dialogue",
    links: [
      { href: "/dialogues", label: "Dialogues", icon: "D", routes: ["dialogues"] },
      { href: "/dialogue-lines", label: "Lines", icon: "L", routes: ["dialogue-lines"] },
      { href: "/dialogue-transitions", label: "Transitions", icon: "T", routes: ["dialogue-transitions"] },
    ],
  },
  {
    label: "Source data",
    links: [
      { href: "/characters", label: "Characters", icon: "C", routes: ["characters"] },
      { href: "/character-sounds", label: "Sounds", icon: "S", routes: ["character-sounds"] },
    ],
  },
  {
    label: "Definitions",
    links: [
      { href: "/definitions/races", label: "Races", icon: "R", routes: ["races"] },
      { href: "/definitions/character-classes", label: "Classes", icon: "C", routes: ["character-classes"] },
      { href: "/definitions/kits", label: "Kits", icon: "K", routes: ["kits"] },
      { href: "/definitions/identifier-definitions", label: "Identifiers", icon: "I", routes: ["identifier-definitions"] },
    ],
  },
  {
    label: "System",
    links: [
      { href: "/pipeline", label: "Pipeline", icon: "P", routes: ["pipeline"] },
      { href: "/extraction-runs", label: "Extraction runs", icon: "R", routes: ["extraction-runs"] },
    ],
  },
];

interface PageProps {
  installation: Installation | null;
}

const STATIC_PAGES: Partial<Record<AppRoute["name"], ComponentType<PageProps>>> = {
  "dialogue-lines": DialogueLineBrowser,
  "dialogue-transitions": TransitionBrowser,
  "character-sounds": SoundBrowser,
  "extraction-runs": ExtractionRunsPage,
  races: RaceBrowser,
  "character-classes": ClassBrowser,
  kits: KitBrowser,
  "identifier-definitions": IdentifierBrowser,
};

export default function App() {
  const route = useRoute();
  const [installation, setInstallation] = useState<Installation | null>(null);
  const [installationError, setInstallationError] = useState<string | null>(null);

  useEffect(() => {
    if (window.location.pathname === "/") navigate("/voices", true);
  }, []);

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
      <DesktopNavigation route={route} installation={installation} />
      <MobileNavigation route={route} />
      <main className="page-main">
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
  return (
    <header className="mobile-topbar">
      <div className="mobile-topbar-head">
        <Brand />
        <span className="read-only"><i /> Read only</span>
      </div>
      <nav className="mobile-nav" aria-label="Pipeline resources">
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
  const active = link.routes.includes(route.name);
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
  const Page = STATIC_PAGES[route.name];
  return Page == null ? <NotFound /> : <Page installation={installation} />;
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
