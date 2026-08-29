import { createServerFn } from "@tanstack/react-start";
import {
  defaultRoot,
  inspectRoot,
  listPresets,
  listSkillStores,
  loadGraph,
  loadPage,
  STREAM_BATCH,
} from "./scan.server";

export const getBootstrap = createServerFn({ method: "GET" }).handler(async () => {
  const skills = listSkillStores().filter((s) => s.format === "atlas");
  return {
    defaultRoot: defaultRoot(),
    presets: skills.length ? skills : listPresets().filter((s) => s.format === "atlas"),
  };
});

export const probeRoot = createServerFn({ method: "POST" })
  .validator((d: { root: string }) => d)
  .handler(async ({ data }) => inspectRoot(data.root));

export const getGraph = createServerFn({ method: "GET" })
  .validator((d: { root: string; offset?: number; limit?: number }) => d)
  .handler(async ({ data }) =>
    loadGraph(data.root, {
      offset: data.offset ?? 0,
      limit: data.limit ?? STREAM_BATCH,
    }),
  );

export const getPage = createServerFn({ method: "POST" })
  .validator((d: { root: string; nodeId: string }) => d)
  .handler(async ({ data }) => loadPage(data.root, data.nodeId));
