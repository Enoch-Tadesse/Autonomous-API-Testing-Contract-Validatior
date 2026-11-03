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
