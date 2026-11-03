import { useEffect, useState } from "react";

export type Route = { page: "overview" } | { page: "runs" } | { page: "run"; id: string } | { page: "eval" };

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/");
  if (parts[0] === "run" && parts[1]) return { page: "run", id: parts[1] };
  if (parts[0] === "runs") return { page: "runs" };
  if (parts[0] === "eval") return { page: "eval" };
  return { page: "overview" };
}

/** Tiny hash router: deep links like #/run/run_ab12cd34 survive a refresh and can be shared. */
export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parse(window.location.hash));
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export const go = (path: string) => {
  window.location.hash = path;
};
