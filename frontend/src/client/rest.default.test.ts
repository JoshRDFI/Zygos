import { afterEach, expect, test, vi } from "vitest";
import { DefaultModelError, resetDefaultModel, setDefaultModel } from "./rest";
import put409 from "../surfaces/fixtures/put-409-confirm.json";
import put404 from "../surfaces/fixtures/put-404.json";
import saved from "../surfaces/fixtures/models-default-saved.json";

afterEach(() => vi.restoreAllMocks());
const reply = (status: number, body: unknown) =>
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(body), { status }));

test("setDefaultModel PUTs provider/model/confirm and returns the view", async () => {
  const f = reply(200, saved);
  const v = await setDefaultModel("ollama", "gemma4:e4b", true);
  expect(v.default?.source).toBe("saved");
  expect(f).toHaveBeenCalledWith("/models/default", expect.objectContaining({ method: "PUT" }));
  const init = f.mock.calls[0][1] as RequestInit;
  expect(JSON.parse(init.body as string)).toEqual({ provider: "ollama", model: "gemma4:e4b", confirm: true });
});

test("a 409 with needs_confirm throws a DefaultModelError carrying it", async () => {
  reply(409, put409);
  const e = await setDefaultModel("ollama", "huge:405b", false).catch((x) => x);
  expect(e).toBeInstanceOf(DefaultModelError);
  expect(e).toMatchObject({ status: 409, detail: put409.detail, needsConfirm: true });
});

test("a 404 throws with the detail and no needsConfirm", async () => {
  reply(404, put404);
  const e = await setDefaultModel("ollama", "nope:1b", false).catch((x) => x);
  expect(e).toMatchObject({ status: 404, detail: put404.detail, needsConfirm: false });
});

test("resetDefaultModel sends DELETE", async () => {
  const f = reply(200, saved);
  await resetDefaultModel();
  expect(f).toHaveBeenCalledWith("/models/default", expect.objectContaining({ method: "DELETE" }));
});
