/** Human descriptions for the target API's switches, shown in the New run panel. */
export const BUGS: Record<string, { title: string; detail: string }> = {
  BUG_RADIUS_MIN: { title: "Radius lower bound", detail: "accepts radius ≤ 0 with 200" },
  BUG_DISTANCE_STRING: { title: "Distance as string", detail: "breaks the response schema" },
  BUG_MISSING_LNG_500: { title: "Missing lng → 500", detail: "server error instead of 400" },
  BUG_AUTH_BYPASS: { title: "Auth bypass", detail: "favorites without a token" },
};

export const FAULTS: Record<string, { title: string; detail: string }> = {
  FAULT_503_THEN_OK: { title: "Flaky 503", detail: "two 503s, then normal" },
  FAULT_TIMEOUT_ALWAYS: { title: "Hanging endpoint", detail: "/v1/favorites never answers" },
};

export interface Preset {
  name: string;
  spec: string;
  bugs: string[];
  faults: string[];
  interactive: boolean;
  blurb: string;
}

export const PRESETS: Preset[] = [
  { name: "Showcase", spec: "standard", bugs: ["BUG_RADIUS_MIN"], faults: ["FAULT_503_THEN_OK"], interactive: false,
    blurb: "retry, rerun, replan, confirmed finding" },
  { name: "Clean API", spec: "standard", bugs: [], faults: [], interactive: false,
    blurb: "false-positive check: expect 0 findings" },
  { name: "All bugs", spec: "standard", bugs: Object.keys(BUGS), faults: [], interactive: false,
    blurb: "four defect classes in one run" },
  { name: "Ask me", spec: "undocumented", bugs: [], faults: [], interactive: true,
    blurb: "agent pauses and asks you a question" },
];

export type HelpKey = "scenario" | "spec" | "bugs" | "faults" | "ask";

/** Text for the info tooltips on the New run panel. */
export const HELP: Record<HelpKey, { title: string; lines: string[] }> = {
  scenario: {
    title: "Scenario presets fill in the whole form",
    lines: [
      "Showcase: radius bug + flaky 503. Shows retry, rerun, replan and one confirmed finding.",
      "Clean API: nothing broken. A correct API should get 0 findings (false-positive check).",
      "All bugs: four defect types (validation, schema, server error, auth) in one run.",
      "Ask me: undocumented spec. The agent pauses and asks you what to expect.",
      "Changing any option below turns it into a custom run.",
    ],
  },
  spec: {
    title: "The contract the agent tests the API against",
    lines: [
      "This file and the target URL are the agent's only input.",
      "Standard: the full contract (target_api/openapi.yaml): limits, required params, error codes, schemas.",
      "Undocumented: same, but it does not say what /v1/favorites returns without a token, so the agent searches the docs and asks you.",
      "Paste: your own OpenAPI YAML or JSON. Requests still go to the demo API on :9000.",
    ],
  },
  bugs: {
    title: "Deliberate contract violations in the demo API",
    lines: [
      "Hidden from the agent: they are switched on inside the demo API before the run (no restart), and the agent has to discover them.",
      "Radius lower bound: radius ≤ 0 accepted → validation finding, then follow-up tests at -1 and -100.",
      "Distance as string: breaks the response schema → schema finding.",
      "Missing lng → 500: crashes instead of 400 → server error finding.",
      "Auth bypass: favorites without a token → auth finding.",
    ],
  },
  faults: {
    title: "Infrastructure trouble, not contract bugs",
    lines: [
      "Hidden from the agent: they make the demo API unreliable, to test that the agent stays reliable.",
      "Flaky 503: two failures, then normal. The agent retries with backoff and recovers.",
      "Hanging endpoint: /v1/favorites never answers. Tests time out and are marked inconclusive, not defects, and the report is still written.",
    ],
  },
  ask: {
    title: "Human in the loop",
    lines: [
      "On: when the spec does not say what a case should return, the run pauses and asks you. Answer a status code (e.g. 401) or 'skip'.",
      "Off: the agent marks such cases inconclusive and keeps going.",
      "Only matters when the spec has gaps (the Undocumented spec or your own).",
    ],
  },
};
